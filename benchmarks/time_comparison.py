__author__ = 'christopher'
from ase.atoms import Atoms
import ase.io as aseio

from pyiid.wrappers.elasticscatter import wrap_atoms
from pyiid.calc.pdfcalc import PDFCalc
from pyiid.utils import build_sphere_np

import matplotlib.pyplot as plt
from pprint import pprint
import time
from copy import deepcopy as dc
from collections import OrderedDict
import pickle
from pyiid.wrappers.elasticscatter import ElasticScatter
import traceback

exp = None
scat = ElasticScatter()

type_list = []
time_list = []
benchmarks = [('CPU', 'flat'), ('Multi-GPU', 'flat')]
colors=['b', 'r']
sizes = range(10, 105, 5)
print sizes

for proc, alg in benchmarks:
    scat.set_processor(proc, alg)
    type_list.append((proc, alg))
    nrg_l = []
    f_l = []
    try:
        for i in sizes:
            atoms = build_sphere_np('/mnt/work-data/dev/pyIID/benchmarks/1100138.cif', float(i) / 2)
            atoms.rattle()
            print len(atoms), i/10.
            calc = PDFCalc(obs_data=pdf, scatter=scat, conv=1, potential='rw')
            atoms.set_calculator(calc)

            s = time.time()
            nrg = atoms.get_potential_energy()
            # scat.get_fq(atoms)
            f = time.time()

            nrg_l.append(f-s)

            s = time.time()
            force = atoms.get_forces()
            # scat.get_grad_fq(atoms)
            f = time.time()
            f_l.append(f-s)
    except:
        print traceback.format_exc()
        pass
    time_list.append((nrg_l, f_l))
# f_name_list = [
    # ('cpu_e.txt', cpu_e), ('cpu_f.txt', cpu_f),
    # ('gpu_e.txt', multi_gpu_e), ('gpu_f.txt', multi_gpu_f)
# ]
# for f_str, lst in f_name_list:
#     with open(f_str, 'w') as f:
#         pickle.dump(lst, f)
#
for i in range(len(benchmarks)):
    for j, (calc_type, line) in enumerate(zip(['energy', 'force'], ['o', 's'])):
        plt.plot(sizes,time_list[i][j], color=colors[i], marker=line, label= '{0} {1}'.format(benchmarks[i], calc_type[0]))
plt.legend(loc='best')
plt.xlabel('NP diameter in Angstrom')
plt.ylabel('time (s) [lower is better]')
plt.savefig('speed.eps', bbox_inches='tight', transparent=True)
plt.savefig('speed.png', bbox_inches='tight', transparent=True)
plt.show()


for i in range(len(benchmarks)):
    for j, (calc_type, line) in enumerate(zip(['energy', 'force'], ['o', 's'])):
        plt.semilogy(sizes,time_list[i][j], color=colors[i], marker=line, label= '{0} {1}'.format(benchmarks[i], calc_type[0]))
plt.legend(loc='best')
plt.xlabel('NP diameter in Angstrom')
plt.ylabel('time (s) [lower is better]')
plt.savefig('speed_log.eps', bbox_inches='tight', transparent=True)
plt.savefig('speed_log.png', bbox_inches='tight', transparent=True)
plt.show()