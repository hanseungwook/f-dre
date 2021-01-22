import argparse
import traceback
import shutil
import logging
import yaml
import sys
import os
import torch
import numpy as np
import torch.utils.tensorboard as tb
sys.path.append(os.path.abspath(os.getcwd()))

from trainers.flow import Flow
# from trainers.classifier import Classifier
import getpass
import wandb

WANDB = {
    'kechoi': 'kristychoi',
    'madeline': 'madeline'
}

torch.set_printoptions(sci_mode=False)

def parse_args_and_config():
    parser = argparse.ArgumentParser(description=globals()['__doc__'])

    # ======== Data and output ========
    parser.add_argument('--config', type=str, required=True, help='Path to the config file')
    parser.add_argument('--exp_id', type=str, help='Exp id; output will be saved in config.data.out_dir/exp_id')
    parser.add_argument('--ni', action='store_true', help='No interaction. Suitable for Slurm Job launcher',)
    parser.add_argument('--seed', type=int, default=1234, help='Random seed')
    parser.add_argument('--verbose', type=str, default='info', help='Verbose level: info | debug | warning | critical',)

    # ======== Flow model task ========
    parser.add_argument('--resume_training', action='store_true', help='Whether to resume training')
    parser.add_argument('--test', action='store_true', help='Whether to test the model; if not true, trains model')
    parser.add_argument('--sample', action='store_true', help='Whether to produce samples from a pretrained model')
    parser.add_argument('--encode_z', action='store_true', help='Whether to encode data using a pretrained model')
    parser.add_argument('--restore_file', default=None, help='If restoring a pretrained flow checkpoint, path to saved model')

    # ======== Sampling: must specify --sample and one of following sampling procedures ========
    parser.add_argument('--generate_samples', action='store_true', help='Regular sampling from flow')
    parser.add_argument('--fair_generate', action='store_true', help='Sample with DRE reweighting using SIR. Must specify --dre_clf_ckpt.')
    parser.add_argument('--fid', action='store_true', help='FID sampling')
    
    # ======== Sampling classifiers: --attr_clf_ckpt for classifying sample attributes, --dre_clf_ckpt for --fair-generate ========
    parser.add_argument('--attr_clf_ckpt', default=None, help='Path to pretrained attribute classifier checkpoint; if provided, classify the flow samples.')
    parser.add_argument('--dre_clf_ckpt', default=None, help='Path to pretrained DRE classifier checkpoint to use for reweighting.')
    
    # ======== Classification-related (TODO: integrate classifier and flow into same main.py?) ========
    parser.add_argument('--classify', action='store_true', help='To run classification')

    args = parser.parse_args()
    # parse config file
    with open(os.path.join('src/flows/configs', args.config), 'r') as f:
        config = yaml.safe_load(f)
    new_config = dict2namespace(config)

    device = torch.device('cuda') if torch.cuda.is_available() else torch.device('cpu')
    logging.info('Using device: {}'.format(device))
    new_config.device = device

    args.out_dir = os.path.join(new_config.training.out_dir, args.exp_id)
    if not os.path.exists(args.out_dir):
        os.makedirs(args.out_dir)
    args.log_path = os.path.join(args.out_dir, 'logs')

    # set up wandb
    if not args.sample:
        # only for training
        wandb.init(
            project='multi-fairgen', 
            entity=WANDB[getpass.getuser()], 
            name=args.exp_id, 
            config=new_config, 
            sync_tensorboard=True,
        )

    # set up logger
    level = getattr(logging, args.verbose.upper(), None)
    if not isinstance(level, int):
        raise ValueError('level {} not supported'.format(args.verbose))

    handler1 = logging.StreamHandler()
    formatter = logging.Formatter(
        '%(levelname)s - %(filename)s - %(asctime)s - %(message)s'
    )
    handler1.setFormatter(formatter)
    logger = logging.getLogger()
    logger.addHandler(handler1)
    logger.setLevel(level)

    if not args.test and not args.sample: # training model
        if not args.resume_training:
            if os.path.exists(args.log_path):
                overwrite = False
                if args.ni:
                    overwrite = True
                else:
                    response = input('Folder already exists. Overwrite? (Y/N)')
                    if response.upper() == 'Y':
                        overwrite = True
                if overwrite:
                    shutil.rmtree(args.log_path)
                    os.makedirs(args.log_path)
                else:
                    print('Folder exists. Program halted.')
                    sys.exit(0)
            else:
                os.makedirs(args.log_path)

            with open(os.path.join(args.log_path, 'config.yml'), 'w') as f:
                yaml.dump(new_config, f, default_flow_style=False)

        # setup logger
        level = getattr(logging, args.verbose.upper(), None)
        if not isinstance(level, int):
            raise ValueError('level {} not supported'.format(args.verbose))

        handler2 = logging.FileHandler(os.path.join(args.log_path, 'stdout.txt'))
        handler2.setFormatter(formatter)
        logger.addHandler(handler2)
        logger.setLevel(level)

    # set random seed
    torch.manual_seed(args.seed)
    np.random.seed(args.seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(args.seed)

    torch.backends.cudnn.benchmark = True

    return args, new_config


def dict2namespace(config):
    namespace = argparse.Namespace()
    for key, value in config.items():
        if isinstance(value, dict):
            new_value = dict2namespace(value)
        else:
            new_value = value
        setattr(namespace, key, new_value)
    return namespace


def main():
    args, config = parse_args_and_config()
    logging.info('Writing log file to {}'.format(args.log_path))
    logging.info('Exp instance id = {}'.format(os.getpid()))
    # logging.info('Exp comment = {}'.format(args.comment))

    try:
        # if args.classify:
        #     trainer = Classifier(args, config)
        # else:
        trainer = Flow(args, config)
        if args.sample:
            trainer.sample(args)
        elif args.test:
            trainer.test()
            # if not args.classify:
            #     trainer.test()  # NOTE: this doesn't work for classifier atm
            # else:
            #     # TODO: FIX THIS (this is the classifier!)
            #     import torch.utils.data as data
            #     from datasets import get_dataset
            #     from models.classifier import build_model

            #     _, test_dataset = get_dataset(args, config)
            #     loader = data.DataLoader(
            #         test_dataset,
            #         batch_size=config.classifier.batch_size//2,
            #         shuffle=False,
            #         num_workers=config.data.num_workers,
            #     )
            #     model_cls = build_model(config.classifier.name)
            #     model = model_cls(config).cuda()
            #     model = torch.nn.DataParallel(model)
            #     state_dict = torch.load(os.path.join(args.log_path, 'clf_ckpt.pth'))[0]
            #     model.load_state_dict(state_dict)
            #     trainer.test(model, loader)
        else:
            trainer.train()
    except Exception:
        logging.error(traceback.format_exc())

    return 0


if __name__ == '__main__':
    sys.exit(main())
