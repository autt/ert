from ert_shared.ensemble_evaluator.config import load_config
from ert_shared.ensemble_evaluator.evaluator import EnsembleEvaluator
from ert_shared.ensemble_evaluator.entity.ensemble import (
    create_ensemble_builder_from_legacy,
)
import uuid
from res.enkf.enums import HookRuntime
from res.enkf import ErtRunContext, EnkfSimulationRunner

from ert_shared.models import BaseRunModel
from ert_shared import ERT
from ert_shared.storage.extraction_api import dump_to_new_storage
from ert_shared.feature_toggling import FeatureToggling


class EnsembleExperiment(BaseRunModel):
    def __init__(self):
        super(EnsembleExperiment, self).__init__(ERT.enkf_facade.get_queue_config())

    def runSimulations__(self, arguments, run_msg):

        run_context = self.create_context(arguments)

        self.setPhase(0, "Running simulations...", indeterminate=False)

        self.setPhaseName("Pre processing...", indeterminate=True)
        self.ert().getEnkfSimulationRunner().createRunPath(run_context)
        EnkfSimulationRunner.runWorkflows(HookRuntime.PRE_SIMULATION, ERT.ert)

        self.setPhaseName(run_msg, indeterminate=False)

        if FeatureToggling.is_enabled("ensemble-evaluator"):
            forward_model = self.ert().resConfig().model_config.getForwardModel()
            queue_config = ERT.enkf_facade.get_queue_config()
            model_config = self.ert().resConfig().model_config
            run_path_list = self.ert().getRunpathList()
            ecl_config = self.ert().resConfig()
            analysis_config = self.ert().analysisConfig()
            res_config = self.ert().resConfig()
            ensemble = create_ensemble_builder_from_legacy(
                run_context,
                forward_model,
                queue_config,
                model_config,
                run_path_list,
                analysis_config,
                ecl_config,
                res_config,
            ).build()

            self.ert().initRun(run_context)

            num_successful_realizations = EnsembleEvaluator(
                ensemble, load_config(), ee_id=str(uuid.uuid1()).split("-")[0]
            ).get_successful_realizations()
        else:
            self._job_queue = self._queue_config.create_job_queue()
            num_successful_realizations = (
                self.ert()
                .getEnkfSimulationRunner()
                .runEnsembleExperiment(self._job_queue, run_context)
            )

        num_successful_realizations += arguments.get("prev_successful_realizations", 0)
        self.checkHaveSufficientRealizations(num_successful_realizations)

        self.setPhaseName("Post processing...", indeterminate=True)
        EnkfSimulationRunner.runWorkflows(HookRuntime.POST_SIMULATION, ERT.ert)
        self.setPhase(1, "Simulations completed.")  # done...

        dump_to_new_storage()

        return run_context

    def runSimulations(self, arguments):
        return self.runSimulations__(arguments, "Running ensemble experiment...")

    def create_context(self, arguments):
        fs_manager = self.ert().getEnkfFsManager()
        result_fs = fs_manager.getCurrentFileSystem()

        model_config = self.ert().getModelConfig()
        runpath_fmt = model_config.getRunpathFormat()
        jobname_fmt = model_config.getJobnameFormat()
        subst_list = self.ert().getDataKW()
        itr = arguments.get("iter_num", 0)
        mask = arguments["active_realizations"]

        run_context = ErtRunContext.ensemble_experiment(
            result_fs, mask, runpath_fmt, jobname_fmt, subst_list, itr
        )

        # Deleting a run_context removes the possibility to retrospectively
        # determine detailed progress. Thus, before deletion, the detailed
        # progress is stored.
        self.updateDetailedProgress()

        self._run_context = run_context
        self._last_run_iteration = run_context.get_iter()
        return run_context

    @classmethod
    def name(cls):
        return "Ensemble Experiment"
