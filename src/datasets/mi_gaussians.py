import os
from PIL import Image
import numpy as np
import torch
from torch.utils.data import Dataset, Subset, TensorDataset
from torch.distributions.multivariate_normal import MultivariateNormal
from scipy.linalg import block_diag
from .looping import LoopingDataset


class EncodedMIGaussians(Dataset):
    def __init__(self, config, split='train'):

        self.config = config
        self.data_dir = config.training.data_dir
        self.perc = config.data.perc
        self.dim = config.data.input_size
        self.split = split

        self.rho = config.data.rho 
        self.mi = self.rho_to_mi()

        self.ref_dset = self.load_dataset(self.split, 'MI', 'ref')
        self.biased_dset = self.load_dataset(self.split, 'MI', 'biased')
        self.joint = self.ref_dset
        print(self.split, len(self.ref_dset), len(self.biased_dset))

    def load_dataset(self, split, dataset, variant):
        fpath = os.path.join(
            self.config.training.data_dir, 
            'encodings', dataset, 
            f'maf_{split}_{variant}_z_perc{self.perc}.npz'
        )
        record = np.load(fpath)
        print('loading dataset from {}'.format(fpath))
        zs = torch.from_numpy(record['z']).float()
        ys = record['y']
        d_ys = torch.ravel(torch.from_numpy(record['d_y']).float())

        # Truncate biased test/val set to be same size as reference val/test
        # if (split == 'test' or split == 'val') and variant == 'biased':
        if (split == 'val') and variant == 'biased':
            # len(self.ref_dset) is always <= len(self.biased_dset)
            zs = zs[:len(self.ref_dset)]
            d_ys = d_ys[:len(self.ref_dset)]
        dataset = TensorDataset(zs, d_ys)
        dataset = LoopingDataset(dataset)
        return dataset

    def rho_to_mi(self):
        """Obtain the ground truth mutual information from rho."""
        # return -0.5 * np.log(1 - self.rho**2) * self.dim
        # HACK!!!
        return -0.5 * np.log(1 - self.rho**2) * (self.dim/2)

    def mi_to_rho(self):
        """Obtain the rho for Gaussian give ground truth mutual information."""
        return np.sqrt(1 - np.exp(-2.0 / self.dim * self.mi))

    def sample_from_joint(self, n):
        # HACK: dim // 2
        x, eps = torch.chunk(torch.randn(n, 2 * self.dim//2), 2, dim=1)
        y = self.rho * x + torch.sqrt(torch.tensor(1. - self.rho**2).float()) * eps
        # joint (ref)
        q = torch.cat([x, y], dim=-1)
        return q

    def __len__(self):
        # return len(self.biased_dset) + len(self.ref_dset)
        return len(self.biased_dset)

    def __getitem__(self, i):
        biased_z, _ = self.biased_dset[i]
        ref_z, _ = self.ref_dset[i]

        return (ref_z, biased_z)


class MIGaussians(Dataset):
    def __init__(self, config, typ, split='train'):

        self.config = config
        self.data_dir = config.training.data_dir
        self.perc = config.data.perc
        self.dim = config.data.input_size
        self.split = split
        self.type = typ
        self.type in ['bias', 'ref']

        self.p_mu = self.config.data.mus[0]
        self.q_mu = self.config.data.mus[1]
        self.mi = float(config.data.mi)
        self.rho = self.mi_to_rho(self.mi) 
        print('instantiating dataset with dim={}, rho={}, MI={}, p_mu={}, q_mu={}'.format(self.dim, self.rho, self.mi, self.p_mu, self.q_mu))

        fpath = os.path.join(self.data_dir, 'gaussians_mi', '{}_d{}_rho{}_pmu{}_qmu{}.npz'.format(self.split, self.dim, self.rho, self.p_mu, self.q_mu))
        try:
            record = np.load(fpath)
        except:
            data_dir = os.path.join(self.data_dir, 'gaussians_mi')
            if not os.path.exists(data_dir):
                os.makedirs(data_dir)
            record = self.generate_data()

        if self.type == 'bias':
            data = record['p']
        else:
            data = record['q']

        # train/val/test split
        if self.type == 'ref' and self.split != 'val':  # keep val same
            to_keep = int(len(data) * self.perc)
            data = data[0:to_keep]
        self.data = torch.from_numpy(data).float()
    
    def generate_data(self):
        # let's just do this to make our lives easier atm
        fpath = os.path.join(self.data_dir, 'gaussians_mi', '{}_d{}_rho{}_pmu{}_qmu{}.npz'.format(self.split, self.dim, self.rho, self.p_mu, self.q_mu))
        if self.split == 'train':
            x, y = self.sample_data(100000)
        elif self.split == 'val':
            x, y = self.sample_data(10000)
        else:
            x, y = self.sample_data(10000)
        x = x.data.numpy()
        y = y.data.numpy()
        np.savez(fpath, **{'p': x, 'q': y})
        
        return {'p': x, 'q': y}

    def rho_to_mi(self):
        """Obtain the ground truth mutual information from rho."""
        # return -0.5 * np.log(1 - self.rho**2) * self.dim
        # HACK!!!
        return -0.5 * np.log(1 - self.rho**2) * (self.dim/2)

    def mi_to_rho(self):
        """Obtain the rho for Gaussian give ground truth mutual information."""
        # return np.sqrt(1 - np.exp(-2.0 / self.dim * self.mi))
        x = (4 * self.mi) / self.dim
        return np.sqrt(1 - np.exp(-x))

    def sample_data(self, batch_size=128):
        """Generate samples from a correlated Gaussian distribution."""
        
        mu1 = torch.empty((self.dim), dtype=torch.float32).fill_(self.p_mu)
        mu2 = torch.empty((self.dim), dtype=torch.float32).fill_(self.q_mu)

        scale_p = block_diag(*[[[1, self.rho], [self.rho, 1]] for _ in range(self.dim // 2)])
        scale_q = torch.eye(self.dim, dtype=torch.float32)

        p_dist = MultivariateNormal(
            loc=mu1,
            covariance_matrix=scale_p,
        )

        q_dist = MultivariateNormal(
            loc=mu2,
            covariance_matrix=scale_q,
        )

        p_samples = p_dist.sample((batch_size,))
        q_samples = q_dist.sample((batch_size,))

        return p_samples, q_samples

    def sample_from_joint(self, n):
        # HACK: dim // 2
        x, eps = torch.chunk(torch.randn(n, 2 * self.dim//2), 2, dim=1)
        y = self.rho * x + torch.sqrt(torch.tensor(1. - self.rho**2).float()) * eps
        # joint (ref)
        q = torch.cat([x, y], dim=-1)
        return q

    def __len__(self):
        return len(self.data)

    def __getitem__(self, i):
        item = self.data[i]
        if self.type == 'bias':
            label = torch.zeros(1)
        else:
            label = torch.ones(1)

        return item, label


class GaussiansForMI(Dataset):
    """
    Generating p(x,y) and p(x)p(y) for MI estimation
    """
    def __init__(self, config, split='train'):

        self.config = config
        self.data_dir = config.training.data_dir
        self.perc = config.data.perc
        self.dim = config.data.input_size
        self.split = split

        self.p_mu = self.config.data.mus[0]
        self.q_mu = self.config.data.mus[1]
        self.mi = float(config.data.mi)
        self.rho = self.mi_to_rho() # Uses saved self.mi variable above
        print('instantiating dataset with dim={}, rho={}, MI={}, p_mu={}, q_mu={}'.format(self.dim, self.rho, self.mi, self.p_mu, self.q_mu))

        fpath = os.path.join(self.data_dir, 'gaussians_mi', '{}_d{}_rho{}.npz'.format(self.split, self.dim, self.rho))
        try:
            record = np.load(fpath)
        except:
            data_dir = os.path.join(self.data_dir, 'gaussians_mi')
            if not os.path.exists(data_dir):
                os.makedirs(data_dir)
            record = self.generate_data()
        self.p = torch.from_numpy(record['p'])
        self.q = torch.from_numpy(record['q'])
        self.joint = self.p

    def generate_data(self):
        # let's just do this to make our lives easier atm
        fpath = os.path.join(self.data_dir, 'gaussians_mi', '{}_d{}_rho{}_pmu{}_qmu{}.npz'.format(self.split, self.dim, self.rho, self.p_mu, self.q_mu))
        if self.split == 'train':
            x, y = self.sample_data(100000)
        elif self.split == 'val':
            x, y = self.sample_data(10000)
        else:
            x, y = self.sample_data(10000)
        x = x.data.numpy()
        y = y.data.numpy()
        np.savez(fpath, **{'p': x, 'q': y})
        
        return {'p': x, 'q': y}

    def sample_data(self, batch_size=128):
        """Generate samples from a correlated Gaussian distribution."""
        
        mu1 = torch.empty((self.dim), dtype=torch.float32).fill_(self.p_mu)
        mu2 = torch.empty((self.dim), dtype=torch.float32).fill_(self.q_mu)

        scale_p = torch.from_numpy(block_diag(*[[[1, self.rho], [self.rho, 1]] for _ in range(self.dim // 2)])).float()
        scale_q = torch.eye(self.dim, dtype=torch.float32)

        p_dist = MultivariateNormal(
            loc=mu1,
            covariance_matrix=scale_p,
        )

        q_dist = MultivariateNormal(
            loc=mu2,
            covariance_matrix=scale_q,
        )

        p_samples = p_dist.sample((batch_size,))
        q_samples = q_dist.sample((batch_size,))

        return p_samples, q_samples

    # def sample_from_joint(self, n):
    #     # HACK: dim // 2
    #     x, eps = torch.chunk(torch.randn(n, 2 * self.dim//2), 2, dim=1)
    #     y = self.rho * x + torch.sqrt(torch.tensor(1. - self.rho**2).float()) * eps
    #     # joint (ref)
    #     q = torch.cat([x, y], dim=-1)
    #     return q

    def rho_to_mi(self):
        """Obtain the ground truth mutual information from rho."""
        # return -0.5 * np.log(1 - self.rho**2) * self.dim
        # HACK!!!
        return -0.5 * np.log(1 - self.rho**2) * (self.dim/2)

    def mi_to_rho(self):
        """Obtain the rho for Gaussian give ground truth mutual information."""
        # return np.sqrt(1 - np.exp(-2.0 / self.dim * self.mi))
        x = (4 * self.mi) / self.dim
        return np.sqrt(1 - np.exp(-x))
    
    def __getitem__(self, index):
        q = self.q[index].float()  # joint 
        p = self.p[index].float()  # prod of marginals

        return (q, p)
    
    def __len__(self):
        # return len(self.p) + len(self.q)
        return len(self.p)  # iterating through both