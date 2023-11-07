# The MIT License (MIT)
# Copyright © 2023 Yuma Rao
# TODO(developer): Set your name
# Copyright © 2023 <your name>

# Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated
# documentation files (the “Software”), to deal in the Software without restriction, including without limitation
# the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software,
# and to permit persons to whom the Software is furnished to do so, subject to the following conditions:

# The above copyright notice and this permission notice shall be included in all copies or substantial portions of
# the Software.

# THE SOFTWARE IS PROVIDED “AS IS”, WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO
# THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL
# THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION
# OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER
# DEALINGS IN THE SOFTWARE.

__version__ = "0.0.0"
version_split = __version__.split(".")
__spec_version__ = (
    (1000 * int(version_split[0]))
    + (10 * int(version_split[1]))
    + (1 * int(version_split[2]))
)
NETUID = 9

n_eval_pages = 2
batch_size = 3
sequence_length = 512

from . import model as model
from . import dataset as dataset

import wandb
import bittensor as bt
from tqdm import tqdm
from datetime import datetime

def get_valid_runs( metagraph ):
    api = wandb.Api( timeout = 100 )
    runs = api.runs("opentensor-dev/openpretraining")
    pbar = tqdm( runs , desc="Getting runs:", leave=False )
    valid_runs = {}
    model_timestamps = {}
    for run in pbar:
        pbar.set_description(f"Checking: {run.id}")

        # Find hotkey of continue
        if 'hotkey' not in run.config: continue
        hotkey = run.config['hotkey']

        # Filter models not registered
        if hotkey not in metagraph.hotkeys: continue
        uid = metagraph.hotkeys.index( hotkey )

        # Find signature or continue
        if 'signature' not in run.config: continue
        signature = run.config['signature']

        # Check signature
        keypair = bt.Keypair( ss58_address = hotkey )
        is_legit = keypair.verify( run.id, bytes.fromhex( signature ) )
        if not is_legit: continue

        # Check for model
        try:
            model_artifact = run.file('model.pth')
        except: continue

        # Check if it is the latest model
        model_timestamp = int(datetime.strptime(model_artifact.updatedAt, '%Y-%m-%dT%H:%M:%S').timestamp())
        if hotkey in model_timestamps and model_timestamps[hotkey] > model_timestamp:
            continue

        # Set run as valid with and latest.
        valid_runs[hotkey] = {
            'uid': uid, 
            'hotkey': hotkey,
            'emission': metagraph.E[uid].item(),
            'run': run, 
            'model_artifact': model_artifact, 
            'timestamp': model_timestamp, 
        }  

    return valid_runs