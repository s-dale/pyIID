from __future__ import print_function

"""
The main class in this module `ElasticScatter` holds the experimental details,
and processor information needed to calculate the elastic powder scattering
from a collection of atoms.
"""
import math
import numpy as np
from accelerate import cuda
from pyiid.experiments.elasticscatter.cpu_wrappers.nxn_cpu_wrap import \
    wrap_fq_grad as cpu_wrap_fq_grad, wrap_fq as cpu_wrap_fq
from pyiid.experiments.elasticscatter.kernels.master_kernel import \
    grad_pdf as cpu_grad_pdf, get_pdf_at_qmin, get_scatter_array
from scipy.interpolate import griddata

__author__ = 'christopher'

all_changes = ['positions', 'numbers', 'cell', 'pbc', 'charges', 'magmoms',
               'exp']


def check_mpi():
    # Test if MPI GPU is viable
    # Currently no working MPI GPU implementation
    return False


def check_gpu():
    """
    Check if GPUs are available on this machine
    """
    try:
        cuda.cuda.gpus.lst
        tf = True
    except cuda.cuda.CudaSupportError:
        tf = False
    return tf


def check_cudafft():
    try:
        from accelerate.cuda import fft as cufft
        tf = True
    except ImportError:
        tf = False
        print('no cudafft')
        cufft = None
    return tf


class ElasticScatter(object):
    """
    Scatter contains all the methods associated with producing theoretical
    diffraction patterns and PDFs from atomic configurations.  It does not
    include potential energies, such as Rw and chi**2 which are under the
    Calculator object.
    >>>from ase.atoms import Atoms
    >>>import matplotlib.pyplot as plt
    >>>atoms = Atoms('Au4', [[0, 0, 0], [3, 0, 0], [0, 3, 0], [3, 3, 0]])
    >>>a = np.random.random(atoms.positions.shape) * .1
    >>>s = ElasticScatter({'rmax': 5., 'rmin': 2.})
    >>>fq = s.get_pdf(atoms)
    >>>fq2 = s.get_pdf(atoms)
    >>>plt.plot(s.get_r(), fq)
    >>>plt.show()

    """

    def __init__(self, exp_dict=None, verbose=False, seed=None):
        self.verbose = verbose
        self.wrap_atoms_state = None
        if seed is None:
            self.seed = int(np.random.random() * 2 ** 32)
        elif isinstance(seed, int):
            self.seed = seed
        else:
            raise ValueError('Expected an integer!')
        self.rs = np.random.RandomState(self.seed)

        # Currently supported processor architectures, in order of most
        # advanced to least
        self.avail_pro = ['MPI-GPU', 'Multi-GPU', 'CPU']

        # needed parameters to specify an experiment
        self.exp_dict_keys = ['qmin', 'qmax', 'qbin', 'rmin', 'rmax', 'rstep',
                              'sampling']
        # default experimental parameters
        self.default_values = [0.0, 25, .1, 0.0, 40.0, .01, 'full']
        # Initiate the algorithm, processor, and experiments
        self.alg = None
        self.processor = None
        self.exp = None
        self.pdf_qbin = None

        # set the experimental parameters
        self.update_experiment(exp_dict)

        # Just in case something blows up down the line set to the most base
        # processor
        self.fq = cpu_wrap_fq
        self.grad = cpu_wrap_fq_grad
        self.grad_pdf = cpu_grad_pdf
        self.processor = 'CPU'
        self.alg = 'nxn'

        # Get the fastest processor architecture available
        self.set_processor()

    def _wrap_atoms(self, atoms):
        """
        Call this function before applying calculator, it will generate static
        arrays for the scattering, preventing recalculation
    
        Parameters
        -----------
        atoms: ase.Atoms
            The atoms to which scatter factors are added
        """
        if 'qbin' not in self.exp.keys():
            self.exp['qbin'] = .1
        n = len(atoms)
        e_num = atoms.get_atomic_numbers()
        e_set = set(e_num)
        e_list = list(e_set)

        for qbin, name in zip(
                [self.exp['qbin'],
                 self.pdf_qbin],
                ['F(Q) scatter', 'PDF scatter']
        ):
            qmax_bin = int(math.floor(self.exp['qmax'] / qbin))
            set_scatter_array = np.zeros((len(e_set), qmax_bin),
                                         dtype=np.float32)

            # Calculate the element-wise scatter factor array
            get_scatter_array(set_scatter_array, e_num, self.exp['qbin'])
            scatter_array = np.zeros((n, qmax_bin), dtype=np.float32)

            # Disseminate the element wise scatter factors
            for i in range(len(e_set)):
                scatter_array[np.where(atoms.numbers == e_list[i])[0], :] = \
                    set_scatter_array[i, :]

            # Set the new scatter factor array
            if name in atoms.arrays.keys():
                del atoms.arrays[name]
            atoms.set_array(name, scatter_array)
        if self.verbose:
            print(atoms.arrays.keys())

        atoms.info['exp'] = self.exp
        atoms.info['scatter_atoms'] = n

    def _check_wrap_atoms_state(self, atoms):
        """
        Check if we need to recalculate the atomic scatter factors
        Parameters
        ----------
        atoms: ase.Atoms
            The atomic configuration

        Returns
        -------

        """
        t_value = True
        if self.wrap_atoms_state is None:
            if self.verbose:
                print('wrap atoms state')
            t_value = False
        elif 'F(Q) scatter' not in atoms.arrays.keys() or \
                        'PDF scatter' not in atoms.arrays.keys():
            if self.verbose:
                print('no FQ/PDF scatter factors')
            t_value = False
        elif atoms.info['exp'] != self.exp or atoms.info[
            'scatter_atoms'] != len(atoms):
            if self.verbose:
                print('experiment does not match or number of atoms changed')
            t_value = False
        if not t_value:
            if self.verbose:
                print('calculating new scatter factors')
            self._wrap_atoms(atoms)
            self.wrap_atoms_state = atoms
        return t_value

    def update_experiment(self, exp_dict):
        """
        Change the scattering experiment parameters.

        Parameters
        ----------
        exp_dict: dict or None
            Dictionary of parameters to be updated, if None use defaults
        """
        # Should be read in from the gr file, but if not here are some defaults
        if exp_dict is None or bool(exp_dict) is False:
            exp_dict = {}
        for key, dv in zip(self.exp_dict_keys, self.default_values):
            if key not in exp_dict.keys():
                exp_dict[key] = dv

        # If sampling is ns then generate the PDF at
        # the Nyquist Shannon Sampling Frequency
        if exp_dict['sampling'] == 'ns':
            exp_dict['rstep'] = np.pi / exp_dict['qmax']

        self.exp = exp_dict
        # Technically we should use this for qbin
        self.pdf_qbin = np.pi / (self.exp['rmax'] + 6 * 2 * np.pi /
                                 self.exp['qmax'])

    def set_processor(self, processor=None, kernel_type='flat'):
        """
        Set the processor to use for calculating the scattering.  If no
        parameter is given then check for the fastest possible processor
        configuration

        Parameters
        -----------
        processor: ['MPI-GPU', 'Multi-GPU', 'Serial-CPU']
            The processor to use
        kernel_type: ['nxn', 'flat-serial', 'flat']
            The type of algorithm to use

        Returns
        -------
        bool:
            True on successful setup of the algorithm and processor
        """
        # If a processor is given try to use that processor,
        # but check if it is viable first.

        # Changing the processor invalidates the previous results
        if processor is None:
            # Test each processor in order of most advanced to least
            for pro in self.avail_pro:
                if self.set_processor(
                        processor=pro, kernel_type=kernel_type) is not None:
                    break

        elif processor == self.avail_pro[0] and check_mpi() is True:
            from pyiid.experiments.elasticscatter.mpi_wrappers.mpi_gpu_wrap \
                import \
                wrap_fq as multi_node_gpu_wrap_fq
            from pyiid.experiments.elasticscatter.mpi_wrappers.mpi_gpu_wrap \
                import \
                wrap_fq_grad as multi_node_gpu_wrap_fq_grad

            self.fq = multi_node_gpu_wrap_fq
            self.grad = multi_node_gpu_wrap_fq_grad
            self.processor = processor
            return True

        elif processor == self.avail_pro[1] and check_gpu() is True:
            from pyiid.experiments.elasticscatter.gpu_wrappers.gpu_wrap import \
                wrap_fq as flat_fq
            from pyiid.experiments.elasticscatter.gpu_wrappers.gpu_wrap import \
                wrap_fq_grad as flat_grad

            self.fq = flat_fq
            self.grad = flat_grad
            self.alg = 'flat'
            if check_cudafft():
                from pyiid.experiments.elasticscatter.gpu_wrappers.gpu_wrap import \
                    grad_pdf
                self.grad_pdf = grad_pdf
            else:
                self.grad_pdf = cpu_grad_pdf
            self.processor = processor
            return True

        elif processor == self.avail_pro[2]:
            if kernel_type == 'nxn':
                self.fq = cpu_wrap_fq
                self.grad = cpu_wrap_fq_grad
                self.alg = 'nxn'

            elif kernel_type == 'flat':
                from pyiid.experiments.elasticscatter.cpu_wrappers \
                    .flat_multi_cpu_wrap import \
                    wrap_fq, wrap_fq_grad

                self.fq = wrap_fq
                self.grad = wrap_fq_grad
                self.alg = 'flat'

            elif kernel_type == 'flat-serial':
                from pyiid.experiments.elasticscatter.cpu_wrappers \
                    .flat_serial_cpu_wrap import \
                    wrap_fq, wrap_fq_grad

                self.fq = wrap_fq
                self.grad = wrap_fq_grad
                self.alg = 'flat-serial'

            self.grad_pdf = cpu_grad_pdf
            self.processor = processor
            return True

    def check_wrap_atoms_state(self, atoms):
        if self.wrap_atoms_state is None:
            return False
        if 'F(Q) scatter' not in atoms.arrays.keys():
            return False
        if atoms.info['exp'] != self.exp or \
                        atoms.info['scatter_atoms'] != len(atoms):
            return False
        return True

    def get_fq(self, atoms, iq_std=None, noise_distribution=None):
        """
        Calculate the reduced structure factor F(Q)

        Parameters
        ----------
        atoms: ase.Atoms
            The atomic configuration for which to calculate F(Q)
        iq_std: {None, float, ndarray}, optional
            Add noise to the data, if `noise` is a float then assume flat
            gaussian noise with a standard deviation of noise, if an array
            then assume that each point has a gaussian distribution of noise
            with a standard deviation given by noise. Note that this noise is
            noise in I(Q) which is propagated to F(Q)
        noise_distribution: distribution function
            The distribution function to take the scattering pattern

        Returns
        -------
        1darray:
            The reduced structure factor
        """
        if self.check_wrap_atoms_state(atoms) is False:
            if self.verbose:
                print('calculating new scatter factors')
            self._wrap_atoms(atoms)
            self.wrap_atoms_state = atoms
        fq = self.fq(atoms, self.exp['qbin'])
        fq = fq[int(np.floor(self.exp['qmin'] / self.exp['qbin'])):]
        if iq_std is not None:
            fq_std = iq_std * np.abs(self.get_scatter_vector()) / np.abs(
                np.average(atoms.get_array('F(Q) scatter'), axis=0) ** 2)[int(
                np.floor(self.exp['qmin'] / self.exp['qbin'])):]
            if fq_std[0] == 0.0:
                fq_std[0] += 1e-9  # added because we can't have zero noise
            exp_noise = self.rs.normal(0, fq_std)
            fq += exp_noise
        return fq

    def get_pdf(self, atoms, iq_std=None, noise_distribution=np.random.normal):
        """
        Calculate the atomic pair distribution factor, PDF, G(r)

        Parameters
        ----------
        atoms: ase.Atoms
            The atomic configuration for which to calculate the PDF
        iq_std: {None, float, ndarray}, optional
            Add noise to the data, if `noise` is a float then assume flat
            gaussian noise with a standard deviation of noise, if an array
            then assume that each point has a gaussian distribution of noise
            with a standard deviation given by noise. Note that this noise is
            noise in I(Q) which is propagated to F(Q)
        noise_distribution: distribution function
            The distribution function to take the scattering pattern

        Returns
        -------
        1darray:
            The PDF
        """
        if self.check_wrap_atoms_state(atoms) is False:
            if self.verbose:
                print('calculating new scatter factors')
            self._wrap_atoms(atoms)
            self.wrap_atoms_state = atoms
        fq = self.fq(atoms, self.pdf_qbin, 'PDF')
        if iq_std is not None:
            a = np.abs(self.get_scatter_vector(pdf=True))
            b = np.abs(np.average(atoms.get_array('PDF scatter') ** 2, axis=0))
            if hasattr(iq_std, 'shape') and iq_std.shape != a.shape:
                iq_std = griddata(np.arange(0, iq_std.shape), iq_std,
                                  np.arange(
                                      a.shape))
            fq_noise = iq_std * a / b
            if fq_noise[0] == 0.0:
                fq_noise[0] += 1e-9  # added because we can't have zero noise
            exp_noise = self.rs.normal(0, fq_noise)
            fq += exp_noise
        r = self.get_r()
        pdf0 = get_pdf_at_qmin(
            fq,
            self.exp['rstep'],
            self.pdf_qbin,
            r,
            self.exp['qmin']
        )
        return pdf0

    def get_sq(self, atoms, iq_std=None, noise_distribution=np.random.normal):
        """
        Calculate the structure factor S(Q)

        Parameters
        ----------
        atoms: ase.Atoms
            The atomic configuration for which to calculate S(Q)
        iq_std: {None, float, ndarray}, optional
            Add noise to the data, if `noise` is a float then assume flat
            gaussian noise with a standard deviation of noise, if an array
            then assume that each point has a gaussian distribution of noise
            with a standard deviation given by noise. Note that this noise is
            noise in I(Q) which is propagated to F(Q)
        noise_distribution: distribution function
            The distribution function to take the scattering pattern
        Returns
        -------
        1darray:
            The structure factor
        """
        fq = self.get_fq(atoms, iq_std, noise_distribution)
        old_settings = np.seterr(all='ignore')
        sq = (fq / self.get_scatter_vector()) + np.ones(
            self.get_scatter_vector().shape)
        np.seterr(**old_settings)
        sq[np.isinf(sq)] = 0.
        return sq

    def get_iq(self, atoms, iq_std=None, noise_distribution=np.random.normal):
        """
        Calculate the scattering intensity, I(Q)

        Parameters
        ----------
        atoms: ase.Atoms
            The atomic configuration for which to calculate I(Q)
        iq_std: {None, float, ndarray}, optional
            Add noise to the data, if `noise` is a float then assume flat
            gaussian noise with a standard deviation of noise, if an array
            then assume that each point has a gaussian distribution of noise
            with a standard deviation given by noise. Note that this noise is
            noise in I(Q) which is propagated to F(Q)
        noise_distribution: distribution function
            The distribution function to take the scattering pattern
        Returns
        -------
        1darray:
            The scattering intensity
        """
        sq = self.get_sq(atoms, iq_std, noise_distribution)
        f2 = np.average(atoms.get_array('F(Q) scatter'), axis=0) ** 2
        iq = sq * f2[int(np.floor(self.exp['qmin'] / self.exp['qbin'])):]
        return iq

    def get_2d_scatter(self, atoms, pixel_array):
        """
        Calculate the scattering intensity as projected onto a detector

        Parameters
        ----------
        atoms: ase.Atoms
            The atomic configuration for which to calculate I(Q)
        pixel_array: 2darray
            A map from Q to the xy coordinates of the detector, each element
            has a Q value
        Returns
        -------
        2darray:
            The scattering intensity on the detector
        """

        iq = self.get_iq(atoms)
        s = self.get_scatter_vector()
        qb = self.exp['qbin']
        final_shape = pixel_array.shape
        fp = pixel_array.ravel()
        img = np.zeros(fp.shape)
        for sub_s, i in zip(s, iq):
            c = np.intersect1d(np.where(sub_s - qb / 2. < fp)[0],
                               np.where(sub_s + qb / 2. > fp)[0])
            img[c] = i
        return img.reshape(final_shape)

    def get_grad_fq(self, atoms):
        """
        Calculate the gradient of the reduced structure factor F(Q)

        Parameters
        ----------
        atoms: ase.Atoms
            The atomic configuration for which to calculate grad F(Q)
        Returns
        -------
        3darray:
            The gradient of the reduced structure factor
        """
        if self.check_wrap_atoms_state(atoms) is False:
            if self.verbose:
                print('calculating new scatter factors')
            self._wrap_atoms(atoms)
            self.wrap_atoms_state = atoms
        g = self.grad(atoms, self.exp['qbin'])
        return g[:, :, int(np.floor(self.exp['qmin'] / self.exp['qbin'])):]

    def get_grad_pdf(self, atoms):
        """
        Calculate the gradient of the PDF

        Parameters
        ----------
        atoms: ase.Atoms
            The atomic configuration for which to calculate grad PDF
        Returns
        -------
        3darray:
            The gradient of the PDF
        """
        if self.check_wrap_atoms_state(atoms) is False:
            if self.verbose:
                print('calculating new scatter factors')
            self._wrap_atoms(atoms)
            self.wrap_atoms_state = atoms
        fq_grad = self.grad(atoms, self.pdf_qbin, 'PDF')
        qmin_bin = int(self.exp['qmin'] / self.pdf_qbin)
        fq_grad[:, :, :qmin_bin] = 0.
        rgrid = self.get_r()

        pdf_grad = self.grad_pdf(fq_grad, self.exp['rstep'], self.pdf_qbin,
                                 rgrid,
                                 self.exp['qmin'])
        return pdf_grad

    def get_scatter_vector(self, pdf=False):
        """
        Calculate the scatter vector Q for the current experiment

        Parameters
        ----------
        pdf: bool
            If true return the PDF rendering scatter vector

        Returns
        -------
        1darray:
            The Q range for this experiment
        """
        if pdf:
            return np.arange(0.,
                             math.floor(self.exp['qmax'] / self.pdf_qbin) *
                             self.pdf_qbin, self.pdf_qbin)
        return np.arange(self.exp['qmin'], math.floor(self.exp['qmax'] /
                                                      self.exp['qbin']) *
                         self.exp['qbin'],
                         self.exp['qbin'])

    def get_r(self):
        """
        Calculate the inter-atomic distance range for the current experiment

        Returns
        -------
        1darray:
            The r range for this experiment
        """
        return np.arange(self.exp['rmin'], self.exp['rmax'], self.exp['rstep'])
