import os
import logging
import torch
import json
import random
import shutil
import torch.backends.cudnn as cudnn
import torch.distributed as dist

from utils.topology import FCGraph
from utils import log
from utils import checkpoint
from utils.helper import AttrDict

logger = logging.getLogger('mlbench')


class Context(object):
    """A global object live through the whole training process."""

    def __init__(self, optimizer, dataset, model, controlflow, meta, runtime):
        """
        Parameters
        ----------
        optimizer : {AttrDict}
            configuration of an optimizer (including the scheduler).
        dataset : {AttrDict}
            configuration of a dataset and batch information.
        model : {AttrDict}
            configuration of a model
        controlflow : {AttrDict}
            configuration of a control flow.
        meta : {AttrDict}
            configuration about setting up environment and logging behavior.
        runtime : {AttrDict}
            containing information of current training stage.
            Only runtime will be checkpointed.
        """
        self.optimizer = optimizer
        self.dataset = dataset
        self.model = model
        self.controlflow = controlflow
        self.meta = meta
        self.runtime = runtime

    def log(self, context_type='dataset'):
        """Log context information."""
        log.centering(context_type, 0, symbol='=', length=80)
        obj = eval("self.{}".format(context_type))
        key_len = max(map(len, obj.keys()))
        for k, v in obj.items():
            log.info("{:<{x}} {:<{y}}".format(k, str(v), x=key_len, y=80-key_len), 0)


def _init_context(args):
    """Initialize context from argument, config file, and default values.

    Default values are provided for each class of context. If the value of a field
    is also given by arguments, then overwrite default values with arguments. If 
    the configuration file is provided, then overwrite those fields.

    Parameters
    ----------
    args : {argparse.Namespace}
        parsed arguments.

    Returns
    -------
    Context
        A context object with configurations for all of the training process.
    """
    config_file = args.config_file

    default_meta = {
        'logging_level': eval('logging.' + args.logging_level.upper()),
        'logging_file': 'mlbench.log',
        'checkpoint_root': '/checkpoint',
        # For debug mode, overwrite checkpoint
        'use_cuda': not args.no_cuda,
        'backend': 'mpi',
        'manual_seed': args.seed,
        'mode': 'develop',
        'debug': args.debug,
        'topk': (1, 5),
        'metrics': 'accuracy',
        'run_id': args.run_id,
        'resume': args.resume,
        # save `all` or save `best` or None
        'save': 'all',
        'cudnn_deterministic': False,
    }

    default_optimizer = {
        "name": "sgd",
        "lr_init": 0.1,
        "momentum": 0.9,
        'criterion': 'CrossEntropyLoss',
        'nesterov': True,
        'weight_decay': 5e-4,
    }

    default_controlflow = {
        'name': 'train_val',
        'avg_model': True,
        'start_epoch': 0,
        'num_epochs': 1,
    }

    default_dataset = {
        'name': 'mnist',
        'root_folder': '/datasets/torch',
        'batch_size': 256,
        'num_workers': 0,
        'train': True,
        'val': True,
        'reshuffle_per_epoch': False,
        'num_classes': 10
    }

    default_model = {
        'name': 'testnet',
    }

    default_runtime = {
        'current_epoch': 0,
        'best_prec1': -1,
        'best_epoch': [],
    }

    if config_file is not None:
        with open(config_file, 'r') as f:
            config = json.load(f)

        default_optimizer.update(config.get('optimizer', {}))
        default_controlflow.update(config.get('controlflow', {}))
        default_dataset.update(config.get('dataset', {}))
        default_model.update(config.get('model', {}))
        default_runtime.update(config.get('runtime', {}))
        default_meta.update(config.get('meta', {}))

    return Context(AttrDict(default_optimizer), AttrDict(default_dataset), AttrDict(default_model),
                   AttrDict(default_controlflow), AttrDict(default_meta), AttrDict(default_runtime))


def config_logging(context):
    """Setup logging modules."""
    level = context.meta.logging_level
    logging_file = context.meta.logging_file

    class RankFilter(logging.Filter):
        def filter(self, record):
            record.rank = dist.get_rank()
            return True

    logger = logging.getLogger('mlbench')
    logger.setLevel(level)
    logger.addFilter(RankFilter())

    formatter = logging.Formatter('%(asctime)s %(name)s %(rank)s %(levelname)s: %(message)s',
                                  "%Y-%m-%d %H:%M:%S")
    ch = logging.StreamHandler()
    ch.setLevel(level)
    ch.setFormatter(formatter)
    logger.addHandler(ch)

    fh = logging.FileHandler(logging_file)
    fh.setLevel(level)
    fh.setFormatter(formatter)
    logger.addHandler(fh)


def config_pytorch(meta):
    """Config packages.

    Fix random number for packages and initialize distributed environment for pytorch.
    Setup cuda environment for pytorch.

    Parameters
    ----------
    meta : {AttrDict}
        Configurations of metadata.
    """
    # Setting `cudnn.deterministic = True` will turn on
    # CUDNN deterministic setting which can slow down training considerably.
    # Unexpected behavior may also be observed from checkpoint.
    # See: https: // github.com/pytorch/examples/blob/master/imagenet/main.py
    if meta.cudnn_deterministic:
        cudnn.deterministic = True
        log.warning('You have chosen to seed training. '
                    'This will turn on the CUDNN deterministic setting, '
                    'which can slow down your training considerably! '
                    'You may see unexpected behavior when restarting '
                    'from checkpoints.', 0)

    if meta.manual_seed is not None:
        random.seed(meta.manual_seed)
        torch.manual_seed(meta.manual_seed)

    # define the graph for the computation.
    if meta.use_cuda:
        assert torch.cuda.is_available()

    meta.rank = dist.get_rank()
    meta.world_size = dist.get_world_size()
    meta.graph = FCGraph(meta)

    # enable cudnn accelerator if we are using cuda.
    if meta.use_cuda:
        meta.graph.assigned_gpu_id()
        torch.backends.cudnn.enabled = True
        torch.backends.cudnn.benchmark = True


def config_path(context):
    """Config the path used during the experiments."""

    # Checkpoint for the current run
    context.meta.ckpt_run_dir = checkpoint.get_ckpt_run_dir(
        context.meta.checkpoint_root, context.meta.run_id,
        context.dataset.name, context.model.name, context.optimizer.name)

    if not context.meta.resume:
        log.info("Remove previous checkpoint directory : {}".format(
            context.meta.ckpt_run_dir))
        shutil.rmtree(context.meta.ckpt_run_dir, ignore_errors=True)
    os.makedirs(context.meta.ckpt_run_dir, exist_ok=True)


def init_context(args):
    # Context build from args, file and defaults
    context = _init_context(args)

    if not dist._initialized:
        dist.init_process_group(context.meta.backend)

    config_logging(context)

    config_pytorch(context.meta)

    # Customize configuration based on meta information.
    config_path(context)

    return context
