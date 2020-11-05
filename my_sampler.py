import math
import torch
from torch.utils.data import Sampler
import torch.distributed as dist
import numpy as np
import torch.distributions.dirichlet as Dirichlet


class UnshuffleDistributedSampler(Sampler):
    """Sampler that restricts data loading to a subset of the dataset.

    It is especially useful in conjunction with
    :class:`torch.nn.parallel.DistributedDataParallel`. In such case, each
    process can pass a DistributedSampler instance as a DataLoader sampler,
    and load a subset of the original dataset that is exclusive to it.

    .. note::
        Dataset is assumed to be of constant size.

    Arguments:
        dataset: Dataset used for sampling.
        num_replicas (optional): Number of processes participating in
            distributed training.
        rank (optional): Rank of the current process within num_replicas.
    """

    def __init__(self, dataset, cluster_data=False, Dirichlet=False,alpha=1000,num_replicas=None, rank=None):
        self.cluster_data = cluster_data
        self.Dirichlet=Dirichlet
        self.alpha=alpha
        if num_replicas is None:
            if not dist.is_available():
                raise RuntimeError("Requires distributed package to be available")
            num_replicas = dist.get_world_size()
        if rank is None:
            if not dist.is_available():
                raise RuntimeError("Requires distributed package to be available")
            rank = dist.get_rank()
        self.dataset = dataset
        self.num_replicas = num_replicas
        self.rank = rank
        self.epoch = 0
        print("self.dataset",self.dataset)
        self.num_samples = int(math.ceil(len(self.dataset) * 1.0 / self.num_replicas))
        self.total_size = self.num_samples * self.num_replicas
        self.class_idx = []
        self.class_num=[]
        self.arrange_by_class()

    def arrange_by_class(self):
        self.class_idx = []
        n_samples = len(self.dataset.targets)
        target_class = np.unique(np.array(self.dataset.targets).tolist())
        for y in target_class:
            self.class_num.append(int(sum(self.dataset.targets==y)))
            self.class_idx.extend(np.arange(n_samples)[np.array(self.dataset.targets)==y].tolist())

    def __iter__(self):
        
        if self.Dirichlet:
            D=Dirichlet.Dirichlet(torch.ones(10)/10*self.alpha)
            torch.manual_seed(self.rank)
            P=D.sample()
            Indice_list = torch.Tensor(self.class_idx.copy())
            indices=torch.Tensor()
            sum_num=0
            for p in range(len(P)):
                index_num=torch.round(self.num_samples*P[p])
                if index_num>0:
                    index=torch.randint(0,self.class_num[p],(int(index_num),))
                    index=Indice_list[index+sum_num]
                    sum_num+=self.class_num[p]
                    indices=torch.cat([indices,index])
            sub_idx=torch.randperm(len(indices)).tolist()
            indices=indices[sub_idx]
            return iter(indices.int().tolist())
            
        g = torch.Generator()
        g.manual_seed(0)

        if self.cluster_data:
            indices = torch.randperm(len(self.dataset), generator=g).tolist()
            indices = self.class_idx.copy()
            indices += indices[:(self.total_size - len(indices))]
            indices = np.array(indices).reshape(self.num_replicas,-1)
            for i in range(self.num_replicas):
                sub_idx = torch.randperm(self.num_samples, generator=g).tolist()
                indices[i] = indices[i][sub_idx].copy()
            indices = indices.T.ravel().tolist()
        else:
            indices = torch.randperm(len(self.dataset), generator=g).tolist()
            indices += indices[:(self.total_size - len(indices))]
 
        assert len(indices) == self.total_size
        indices = indices[self.rank:self.total_size:self.num_replicas]
        assert len(indices) == self.num_samples 

        return iter(indices)

    def __len__(self):
        return self.num_samples

    def set_epoch(self, epoch):
        self.epoch = epoch