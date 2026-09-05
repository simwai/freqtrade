"""
Fibonacci Hyperopt - Extended hyperopt engine with multi-stage Fibonacci stepping.

This module provides the FibonacciHyperopt class which extends the base Hyperopt
class to implement multi-stage optimization with progressively narrowing search spaces
based on Fibonacci-numbered trial budgets.
"""

import logging
import random
from datetime import datetime
from math import ceil
from multiprocessing import Manager
from pathlib import Path
from typing import Any

import rapidjson
from joblib import Parallel, cpu_count, delayed, wrap_non_picklable_objects

from freqtrade.constants import FTHYPT_FILEVERSION, LAST_BT_RESULT_FN, Config
from freqtrade.enums import HyperoptState
from freqtrade.exceptions import OperationalException
from freqtrade.misc import file_dump_json, plural
from freqtrade.optimize.hyperopt.fibonacci_stepping import FibonacciStepping
from freqtrade.optimize.hyperopt.hyperopt_logger import logging_mp_handle, logging_mp_setup
from freqtrade.optimize.hyperopt.hyperopt_optimizer import HyperOptimizer
from freqtrade.optimize.hyperopt.hyperopt_output import HyperoptOutput
from freqtrade.optimize.hyperopt_tools import (
    HyperoptStateContainer,
    HyperoptTools,
    hyperopt_serializer,
)
from freqtrade.util import get_progress_tracker


logger = logging.getLogger(__name__)

# Logging queue for joblib child processes. Must live at module scope because
# run_optimizer_parallel is pickled by reference into the workers.
log_queue: Any = None


class FibonacciHyperopt:
    """
    Extended Hyperopt class with Fibonacci stepping multi-stage optimization.

    This class implements a three-stage optimization approach:
    1. Initialization: n_initial random trials
    2. Stage 1: F_n - n_initial trials on full search space
    3. Stage 2: F_{n-1} trials on reduced space (from top Stage 1 results)
    4. Stage 3: F_{n-2} trials on further reduced space (from top Stage 2 results)
    """

    def __init__(self, config: Config) -> None:
        self._hyper_out: HyperoptOutput = HyperoptOutput(streaming=True)

        self.config = config
        self.analyze_per_epoch = self.config.get("analyze_per_epoch", False)
        HyperoptStateContainer.set_state(HyperoptState.STARTUP)

        if self.config.get("hyperopt"):
            raise OperationalException(
                "Using separate Hyperopt files has been removed in 2021.9. Please convert "
                "your existing Hyperopt file to the new Hyperoptable strategy interface"
            )

        time_now = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        strategy = str(self.config["strategy"])
        results_dir = Path(
            self.config.get(
                "hyperopt_results_dir", self.config["user_data_dir"] / "hyperopt_results"
            )
        )
        results_dir.mkdir(parents=True, exist_ok=True)
        result_filename = self.config.get(
            "hyperopt_result_filename", f"strategy_{strategy}_{time_now}.fthypt"
        )
        self.results_file = results_dir / str(result_filename)
        self.data_pickle_file = results_dir / "hyperopt_tickerdata.pkl"

        self.current_best_loss = 100
        self.clean_hyperopt()

        self.num_epochs_saved = 0
        self.current_best_epoch: dict[str, Any] | None = None
        self.interrupted = False

        if HyperoptTools.has_space(self.config, "sell"):
            # Make sure use_exit_signal is enabled
            self.config["use_exit_signal"] = True

        self.print_all = self.config.get("print_all", False)
        self.hyperopt_table_header = 0
        self.print_json = self.config.get("print_json", False)

        self.hyperopter = HyperOptimizer(self.config)

        # Fibonacci stepping
        self.fib_stepping = FibonacciStepping(self.config)
        self.stage_budgets = self.fib_stepping.compute_stage_budgets()
        self.current_stage = "init"
        self.stage_epoch = 0
        self.global_epoch = 0
        self.stage_results: dict[str, list[dict[str, Any]]] = {
            "init": [],
            "stage1_full": [],
            "stage2_reduced": [],
            "stage3_refined": [],
        }

    @staticmethod
    def get_lock_filename(config: Config) -> str:
        return str(config["user_data_dir"] / "hyperopt.lock")

    def clean_hyperopt(self) -> None:
        """
        Remove hyperopt pickle files to restart hyperopt.
        """
        for f in [self.data_pickle_file, self.results_file]:
            p = Path(f)
            if p.is_file():
                logger.info(f"Removing `{p}`.")
                p.unlink()

    def _save_result(self, epoch: dict) -> None:
        """
        Save hyperopt results to file.
        Store one line per epoch.
        While not a valid json object - this allows appending easily.
        :param epoch: result dictionary for this epoch.
        """
        epoch[FTHYPT_FILEVERSION] = 2
        with self.results_file.open("a") as f:
            rapidjson.dump(
                epoch,
                f,
                default=hyperopt_serializer,
                number_mode=rapidjson.NM_NATIVE | rapidjson.NM_NAN,
            )
            f.write("\n")

        self.num_epochs_saved += 1
        logger.debug(
            f"{self.num_epochs_saved} {plural(self.num_epochs_saved, 'epoch')} "
            f"saved to '{self.results_file}'."
        )
        # Store hyperopt filename
        latest_filename = Path.joinpath(self.results_file.parent, LAST_BT_RESULT_FN)
        file_dump_json(latest_filename, {"latest_hyperopt": str(self.results_file.name)}, log=False)

    def print_results(self, results: dict[str, Any]) -> None:
        """
        Log results if it is better than any previous evaluation.
        """
        is_best = results["is_best"]

        if self.print_all or is_best:
            self._hyper_out.add_data(
                self.config,
                [results],
                self.stage_budgets["total"],
                self.print_all,
            )

    def run_optimizer_parallel(self, parallel: Parallel, asked: list[list]) -> list[dict[str, Any]]:
        """Start optimizer in a parallel way"""

        def optimizer_wrapper(*args, **kwargs):
            # global log queue. This must happen in the file that initializes Parallel
            logging_mp_setup(
                log_queue, logging.INFO if self.config["verbosity"] < 1 else logging.DEBUG
            )

            return self.hyperopter.generate_optimizer(*args, **kwargs)

        return parallel(delayed(wrap_non_picklable_objects(optimizer_wrapper))(v) for v in asked)

    def _set_random_state(self, random_state: int | None) -> int:
        return random_state or random.randint(1, 2**16 - 1)  # noqa: S311

    def get_asked_points(self, n_points: int) -> tuple[list[list[Any]], list[bool]]:
        """
        Enforce points returned from `self.opt.ask` have not been already evaluated.

        Steps:
        1. Try to get points using `self.opt.ask` first
        2. Discard the points that have already been evaluated
        3. Retry using `self.opt.ask` up to 3 times
        4. If still some points are missing in respect to `n_points`, random sample some points
        5. Repeat until at least `n_points` points in the `asked_non_tried` list
        6. Return a list with length truncated at `n_points`
        """

        def unique_list(a_list):
            new_list = []
            for item in a_list:
                if item not in new_list:
                    new_list.append(item)
            return new_list

        i = 0
        asked_non_tried: list[list[Any]] = []
        is_random_non_tried: list[bool] = []
        while i < 5 and len(asked_non_tried) < n_points:
            if i < 3:
                self.opt.cache_ = {}
                asked = unique_list(self.opt.ask(n_points=n_points * 5 if i > 0 else n_points))
                is_random = [False for _ in range(len(asked))]
            else:
                asked = unique_list(self.opt.space.rvs(n_samples=n_points * 5))
                is_random = [True for _ in range(len(asked))]
            is_random_non_tried += [
                rand
                for x, rand in zip(asked, is_random, strict=False)
                if x not in self.opt.Xi and x not in asked_non_tried
            ]
            asked_non_tried += [
                x for x in asked if x not in self.opt.Xi and x not in asked_non_tried
            ]
            i += 1

        if asked_non_tried:
            return (
                asked_non_tried[: min(len(asked_non_tried), n_points)],
                is_random_non_tried[: min(len(asked_non_tried), n_points)],
            )
        else:
            return self.opt.ask(n_points=n_points), [False for _ in range(n_points)]

    def evaluate_result(self, val: dict[str, Any], current: int, is_random: bool):
        """
        Evaluate results returned from generate_optimizer.
        """
        self.global_epoch += 1
        self.stage_epoch += 1

        val["current_epoch"] = self.global_epoch
        val["stage_epoch"] = self.stage_epoch
        val["stage"] = self.current_stage

        # For backward compatibility, mark initial points based on global epoch
        # but also track stage-specific initial points
        val["is_initial_point"] = self.global_epoch <= self.stage_budgets["init"]

        logger.debug("Optimizer epoch evaluated: %s", val)

        is_best = HyperoptTools.is_best_loss(val, self.current_best_loss)
        # This value is assigned here and not in the optimization method
        # to keep proper order in the list of results. That's because
        # evaluations can take different time. Here they are aligned in the
        # order they will be shown to the user.
        val["is_best"] = is_best
        val["is_random"] = is_random
        self.print_results(val)

        if is_best:
            self.current_best_loss = val["loss"]
            self.current_best_epoch = val

        # Store in stage-specific results
        self.stage_results[self.current_stage].append(val)
        self._save_result(val)

    def _setup_logging_mp_workaround(self) -> None:
        """
        Workaround for logging in child processes.
        local_queue must be a global in the file that initializes Parallel.
        """
        global log_queue
        m = Manager()
        log_queue = m.Queue()

    def _run_stage(
        self,
        stage_name: str,
        n_trials: int,
        parallel: Parallel,
        is_first_stage: bool = False,
    ) -> list[dict[str, Any]]:
        """
        Run a single optimization stage.

        Args:
            stage_name: Name of the stage (init, stage1_full, stage2_reduced, stage3_refined)
            n_trials: Number of trials for this stage
            parallel: joblib Parallel instance
            is_first_stage: Whether this is the first stage (for analyze_per_epoch handling)

        Returns:
            List of epoch results for this stage
        """
        self.current_stage = stage_name
        self.stage_epoch = 0

        stage_info = self.fib_stepping.get_stage_info(stage_name)
        logger.info(f"Starting {stage_info.get('name', stage_name)}: {n_trials} trials")

        jobs = parallel._effective_n_jobs()
        evals = ceil(n_trials / jobs)

        stage_results = []

        try:
            with get_progress_tracker(cust_callables=[self._hyper_out]) as pbar:
                task = pbar.add_task(f"{stage_info.get('name', stage_name)}", total=n_trials)

                start = 0

                # Handle analyze_per_epoch for first stage only
                if is_first_stage and self.analyze_per_epoch:
                    # First analysis not in parallel mode when using --analyze-per-epoch.
                    # This allows dataprovider to load it's informative cache.
                    asked, is_random = self.get_asked_points(n_points=1)
                    f_val0 = self.hyperopter.generate_optimizer(asked[0])
                    self.opt.tell(asked, [f_val0["loss"]])
                    self.evaluate_result(f_val0, 1, is_random[0])
                    stage_results.append(f_val0)
                    pbar.update(task, advance=1)
                    start += 1

                for i in range(evals):
                    # Correct the number of epochs to be processed for the last
                    # iteration (should not exceed n_trials in total)
                    n_rest = (i + 1) * jobs - (n_trials - start)
                    current_jobs = jobs - n_rest if n_rest > 0 else jobs

                    asked, is_random = self.get_asked_points(n_points=current_jobs)
                    f_val = self.run_optimizer_parallel(parallel, asked)
                    self.opt.tell(asked, [v["loss"] for v in f_val])

                    for j, val in enumerate(f_val):
                        # Use human-friendly indexes here (starting from 1)
                        current = i * jobs + j + 1 + start

                        self.evaluate_result(val, current, is_random[j])
                        stage_results.append(val)
                        pbar.update(task, advance=1)
                    logging_mp_handle(log_queue)

        except KeyboardInterrupt:
            self.interrupted = True
            print("User interrupted..")
            raise

        logger.info(
            f"Completed {stage_info.get('name', stage_name)}: "
            f"{len(stage_results)} epochs saved."
        )

        return stage_results

    def _prepare_next_stage_space(self, stage_name: str) -> None:
        """
        Prepare reduced search space for the next stage based on current stage results.
        """
        if stage_name == "init":
            # After init, we use full space for stage 1
            return

        # Get current stage results
        current_results = self.stage_results.get(stage_name, [])
        if not current_results:
            logger.warning(f"No results for stage {stage_name}, skipping space reduction")
            return

        # Sort by loss (best first)
        sorted_results = sorted(current_results, key=lambda x: x["loss"])

        # Determine k for space reduction (use stage budget or available results)
        if stage_name == "stage1_full":
            k = self.stage_budgets["stage2_reduced"]
        elif stage_name == "stage2_reduced":
            k = self.stage_budgets["stage3_refined"]
        else:
            return

        # Reduce space
        logger.info(f"Reducing search space for next stage based on top {k} results")
        new_dimensions = self.fib_stepping.reduce_space(
            self.hyperopter.dimensions, sorted_results, k
        )

        # Reset optimizer with new dimensions
        logger.info(f"Resetting optimizer with {len(new_dimensions)} dimensions")
        self.hyperopter.reset_optimizer(new_dimensions)

        # Update our reference
        self.opt = self.hyperopter.get_optimizer(
            self.config.get("hyperopt_jobs", -1),
            self.random_state,
            0,  # No additional initial points for subsequent stages
            10,  # SKOPT_MODEL_QUEUE_SIZE
        )

    def start(self) -> dict[str, Any] | None:
        """
        Start the multi-stage Fibonacci hyperopt optimization.

        Returns:
            Best epoch result across all stages, or None if interrupted.
        """
        self.interrupted = False
        self.random_state = self._set_random_state(self.config.get("hyperopt_random_state"))
        logger.info(f"Using optimizer random state: {self.random_state}")
        self.hyperopt_table_header = -1
        self.hyperopter.prepare_hyperopt()

        cpus = cpu_count()
        logger.info(f"Found {cpus} CPU cores. Let's make them scream!")
        config_jobs = self.config.get("hyperopt_jobs", -1)
        logger.info(f"Number of parallel jobs set as: {config_jobs}")

        # Create initial optimizer
        self.opt = self.hyperopter.get_optimizer(
            config_jobs, self.random_state, self.stage_budgets["init"], 10
        )
        self._setup_logging_mp_workaround()

        try:
            with Parallel(n_jobs=config_jobs) as parallel:
                jobs = parallel._effective_n_jobs()
                logger.info(f"Effective number of parallel workers used: {jobs}")

                # Stage 0: Initialization (random trials)
                if self.stage_budgets["init"] > 0:
                    logger.info("=" * 60)
                    logger.info("STAGE 0: INITIALIZATION (Random Exploration)")
                    logger.info("=" * 60)
                    self._run_stage("init", self.stage_budgets["init"], parallel, is_first_stage=True)

                # Stage 1: Full space Bayesian optimization
                if self.stage_budgets["stage1_full"] > 0:
                    logger.info("=" * 60)
                    logger.info("STAGE 1: FULL SPACE BAYESIAN OPTIMIZATION")
                    logger.info("=" * 60)
                    self._run_stage("stage1_full", self.stage_budgets["stage1_full"], parallel)

                    # Prepare reduced space for Stage 2
                    self._prepare_next_stage_space("stage1_full")

                # Stage 2: Reduced space
                if self.stage_budgets["stage2_reduced"] > 0:
                    logger.info("=" * 60)
                    logger.info("STAGE 2: REDUCED SPACE BAYESIAN OPTIMIZATION")
                    logger.info("=" * 60)
                    self._run_stage("stage2_reduced", self.stage_budgets["stage2_reduced"], parallel)

                    # Prepare further reduced space for Stage 3
                    self._prepare_next_stage_space("stage2_reduced")

                # Stage 3: Further refined space
                if self.stage_budgets["stage3_refined"] > 0:
                    logger.info("=" * 60)
                    logger.info("STAGE 3: REFINED SPACE BAYESIAN OPTIMIZATION")
                    logger.info("=" * 60)
                    self._run_stage("stage3_refined", self.stage_budgets["stage3_refined"], parallel)

        except KeyboardInterrupt:
            self.interrupted = True
            print("User interrupted..")

        logger.info(
            f"{self.num_epochs_saved} {plural(self.num_epochs_saved, 'epoch')} "
            f"saved to '{self.results_file}'."
        )

        # Print stage summary
        logger.info("Fibonacci Hyperopt Summary:")
        for stage_name in self.fib_stepping.get_stage_names():
            count = len(self.stage_results.get(stage_name, []))
            stage_info = self.fib_stepping.get_stage_info(stage_name)
            logger.info(f"  {stage_info.get('name', stage_name)}: {count} epochs")

        if self.current_best_epoch:
            HyperoptTools.try_export_params(
                self.config,
                self.hyperopter.get_strategy_name(),
                self.current_best_epoch,
            )

            HyperoptTools.show_epoch_details(
                self.current_best_epoch, self.stage_budgets["total"], self.print_json
            )
        elif self.num_epochs_saved > 0:
            print(
                f"No good result found for given optimization function in {self.num_epochs_saved} "
                f"{plural(self.num_epochs_saved, 'epoch')}."
            )
        else:
            # This is printed when Ctrl+C is pressed quickly, before first epochs have
            # a chance to be evaluated.
            print("No epochs evaluated yet, no best result.")

        return self.current_best_epoch