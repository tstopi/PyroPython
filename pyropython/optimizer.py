import numpy as np
from functools import partial
import sklearn.ensemble as skl
from distutils.dir_util import copy_tree
from shutil import rmtree
from pyropython.initial_design import make_initial_design
from multiprocessing import Manager
from shutil import rmtree,copytree
from traceback import print_exception

class Logger:
    """
    Class for recording optimization algorithm progress.
    """

    def __init__(self,
                 params=None,
                 logfile="log.csv",
                 files = None,
                 best_dir="Best/"):
        self.x_best = None
        self.f_best = None
        self.xi = None
        self.fi = None
        self.iter = 0
        self.logfile = open(logfile, "w")
        self.Xi = []
        self.Fi = []
        self.params = params
        self.files = files
        self.best_dir = best_dir

        # write header to logfile before  first iteration
        header = ",".join(["Iteration"] +
                          [name for name, bounds in self.params] +
                          ["Objective", "Best Objective"])
        self.logfile.write(header+"\n")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, tb):
        self.logfile.close()
        if exc_type is not None:
            print_exception(exc_type, exc_value, tb)


    def __call__(self, x, f, **args):
        """
        This function call signature matches most scipy.optimize callbacks
        """
        self.update(x, f)
        self.print_iteration()
        self.log_iteration()
        self.process_files()

    def update(self, x, f):
        f_ = list(f)
        x_ = list(x)
        self.Xi.append(x_)
        self.Fi.append(f_)
        ind = np.argmin(f_)
        self.fi = f_[ind]
        self.xi = x_[ind]

        if self.f_best:
            if self.f_best > self.fi:
                self.f_best = self.fi
                self.x_best = self.xi
        else:
            self.f_best = self.fi
            self.x_best = self.xi
        self.iter += 1

    def print_iteration(self):
        """ prints the solution from current iteration """
        # Print info
        msg = """
            Iteration: {it:d}
                best objective from this iteration:  {cur:.3E}
                best objective found thus far:       {bst:.3E}
                best model:
              """
        print(msg.format(it=self.iter,cur=self.fi, bst=self.f_best))
        msg = "       {name} :"
        for n, (name, bounds) in enumerate(self.params):
            print(msg.format(name=name), self.x_best[n])
        print()

    def log_iteration(self):
        """ write iteration info to log file """
        line = (["%d" % (self.iter)] + ["%.3f" % v for v in self.xi] +
                ["%3f" % self.fi, "%3f" % self.f_best])
        self.logfile.write(",".join(line)+"\n")
        pass

    def process_files(self):
        if not self.files:
            return
        while not self.files.empty():
            fi, xi, pwd = self.files.get()
            if fi <= self.f_best:
                rmtree(self.best_dir)
                copytree(pwd,self.best_dir)
                rmtree(pwd)


def skopt(case, runopts, executor):
    """ optimize case using scikit-optimize
    """
    from skopt import Optimizer
    optimizer = Optimizer(dimensions=case.get_bounds(),
                          **runopts.optimizer_opts)
    files = Manager().Queue()
    fun = partial(case.fitness, files=files)
    x = make_initial_design(name=runopts.initial_design,
                            num_points=runopts.num_initial,
                            bounds=case.get_bounds())
    N_iter = 0
    with Logger(params=case.params, files=files) as log:
        while N_iter<runopts.max_iter:
            # evaluate points (in parallel)
            y = list(executor.map(fun, x))
            log(x, y)
            optimizer.tell(x ,y)
            if N_iter < runopts.max_iter:
                x = optimizer.ask(runopts.num_points)
            N_iter += 1
        return log.x_best, log.f_best, log.Xi,log.Fi


def basin_hopping(case, runopts, **args):
    """ optimize case using scipy optimize basin hopping algorithm
    """
    from scipy.optimize import basinhopping

    x = make_initial_design(name=runopts.initial_design,
                            num_points=1,
                            bounds=case.get_bounds())

    # Augument case.fitness with penalty function, don't return directory
    def fun(x):
        return (case.fitness(x, return_directory=False) +
                penalty_function(x, case.get_bounds()))

    with Logger(params=case.params) as log:

        opt = basinhopping(fun, x,
                           niter=runopts.max_iter,
                           callback=log)

        return log.x_best, log.f_best, log.points


def multistart(case, runopts, executor):
    """ optimize case using multiple random starts and scipy.minimize
    """
    from scipy.optimize import minimize
    x = make_initial_design(name=runopts.initial_design,
                            num_points=runopts.num_initial,
                            bounds=case.get_bounds())

    N_iter = 0
    files = Manager().Queue()
    fun = partial(case.penalized_fitness, files=files)
    with Logger(params=case.params, files=files) as log:
        while N_iter < runopts.max_iter:
            # evaluate points (in parallel)
            task = partial(minimize, fun,
                           method="powell")
            y = list(executor.map(task, x))
            log(x, y)
            if N_iter < runopts.max_iter:
                x = make_initial_design(name="rand",
                                        num_points=runopts.num_points,
                                        bounds=case.get_bounds())
            N_iter += 1
        return log.x_best, log.f_best, log.Xi, log.Fi



optimizers = {"skopt": skopt,
              "basin_hopping": basin_hopping,
              "multistart": multistart}


def get_optimizer(name="skopt"):
    return optimizers.get(name, skopt)