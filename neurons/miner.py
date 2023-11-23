# The MIT License (MIT)
# Copyright © 2023 Yuma Rao
# Copyright © 2023 const

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

import os
import json
import wandb
import torch
import string
import random
import argparse
import pretrain
import bittensor as bt

# === Config ===
def get_config():
    """
    Set up and parse the command-line arguments to configure the system.

    The configuration is responsible for setting up the environment including
    the model path, device to use, and the bittensor wallet and logging configurations.

    Returns:
        A namespace object containing the configuration parameters.
    """

    # Initialize an argument parser
    parser = argparse.ArgumentParser()

    # Add model_path argument which allows the user to specify the path of the model
    parser.add_argument("--model_path", type=str, required=False, help="Override model path")

    # Add device argument which defaults to 'cuda' if available, else 'cpu'
    parser.add_argument("--device", type=str, default="cuda" if torch.cuda.is_available() else "cpu", help="Device name.")

    # Add device argument which defaults to 'cuda' if available, else 'cpu'
    parser.add_argument("--load_best", action='store_true', help='If set, the miner loads the best model from wandb to train off.' ) 

    # Add device argument which defaults to 'cuda' if available, else 'cpu'
    parser.add_argument("--load_run_id", type=str, default=None, help='If passed loads the model under this run id' )  

    # Add device argument which defaults to 'cuda' if available, else 'cpu'
    parser.add_argument("--continue_id", type=str, default=None, help='If passed continues from the model on the passed run.' )  

    # Set the number of epochs
    parser.add_argument("--num_epochs", type = int, default = -1, help="Number of training epochs (-1 is infinite)")

    # Training lr.
    parser.add_argument("--lr", type = float, default = 0.00001, help="Learning rate.")

    # Training batch size
    parser.add_argument("--bs", type = int, default = pretrain.batch_size, help="Batch size")

    # Training sequence length
    parser.add_argument("--sl", type = int, default = pretrain.sequence_length, help="Sequence length")

    # Training accumulation steps per step.
    parser.add_argument("--accumulation_steps", type = int, default = 5, help="The number of training accumulation steps.")

    # Set the number of pages trained per epoch
    parser.add_argument("--pages_per_epoch", type = int, default=10, help="Number of pages trained on per epoch")

    # Include wallet and logging arguments from bittensor
    bt.wallet.add_args(parser)
    bt.subtensor.add_args(parser)
    bt.logging.add_args(parser)

    # Parse the arguments and create a configuration namespace
    config = bt.config(parser)

    # Expand the user path and create a full path for the model
    config.full_path = os.path.expanduser(
        "{}/{}/{}/netuid{}/{}".format(
            config.logging.logging_dir,
            config.wallet.name,
            config.wallet.hotkey,
            pretrain.NETUID,
            "miner",
        )
    )

    # Set the default model path if it wasn't provided in the command line
    if config.model_path == None:
        config.model_path = config.full_path + '/' + 'model.pth'

    # Create the directory for the model path if it does not exist
    if not os.path.exists(os.path.dirname(config.model_path)):
        os.makedirs(os.path.dirname(config.model_path), exist_ok=True)

    return config

# Parse the configuration
config = get_config()

# Print the entire configuration setup
print(config)

# Create bittensor objects and check uid.
bt.logging( config = config )
wallet = bt.wallet( config = config ) 
subtensor = bt.subtensor( config = config )
metagraph = subtensor.metagraph( pretrain.NETUID )
if wallet.hotkey.ss58_address not in metagraph.hotkeys: 
    bt.logging.error(f"You are not registered. Use `btcli s register --netuid {pretrain.NETUID}` to register.")
    exit()
my_uid = metagraph.hotkeys.index( wallet.hotkey.ss58_address )
bt.logging.success( f'You are registered with address: {wallet.hotkey.ss58_address} and uid: {my_uid}' )

# Initialize and configure the model for pretraining
model = pretrain.model.get_model()  # Get the model from the pretrain module
torch.save(model.state_dict(), config.model_path)
api = wandb.Api( timeout = 100 )


def get_run_from_id( run_id ):
    run_path = f"opentensor-dev/{pretrain.WANDB_PROJECT}/{run_id}"
    bt.logging.success(f'Loading model from path: {run_path}')
    return api.run(run_path)

# Optionall load the model from the passed run id:
def load_model_from_run( run ):
    model_file = run.file("model.pth")
    model_file.download(replace=True, root = os.path.dirname(config.model_path) )
    bt.logging.success(f'Loaded and saved model to: {config.model_path}')

# Model is pulled from specific run.
if config.load_run_id != None:
    bt.logging.success(f'Loading based on --config.load_run_id {config.model_path}')
    load_model_from_run( get_run_from_id( config.load_run_id ) )
    
# Model is pulled from best on network
elif config.load_best:
    bt.logging.success(f'Loading based on --config.load_best')
    best_uid = max(range(256), key=lambda uid: metagraph.I[uid].item())
    print(f"best uid is {best_uid}")
    runs = api.runs(
        f"opentensor-dev/{pretrain.WANDB_PROJECT}",
        filters={
            "config.version": pretrain.__version__,
            "config.type": "miner",
            "config.run_name": {
                "$regex": f"miner-{best_uid}-.*"
            }
        }
    )
    load_model_from_run( get_run_from_id(runs[0].id) )

elif config.continue_id:
    run = get_run_from_id( config.continue_id  )
    run_hotkey = run.config['hotkey']
    load_model_from_run( run )

# Model is reinited fresh.
else:
    bt.logging.success(f'Starting model from scratch')

# Load the model.
model_weights = torch.load( config.model_path, map_location=torch.device(config.device) )
model.load_state_dict( model_weights )
model.zero_grad()  # Reset gradients to zero
model.train()  # Set the model to training mode
model.to(config.device)  # Move the model to the specified device

# Initialize the optimizer
optimizer = torch.optim.AdamW( model.parameters(), lr = config.lr, weight_decay=0.01)

# Loads your wandb run from file or creates a new one.
run_id_file = config.full_path + '/run.json'
try:
    with open( run_id_file, 'r' ) as f:
        run_id = json.load( f )['WANDB_RUN_ID']
        bt.logging.success(f'Continuing run, loaded run_id: {run_id}')
except Exception as e: 
    run_id = wandb.util.generate_id()
    bt.logging.success(f'First run, creating new run_id: {run_id} {e}')

with open( run_id_file, 'w' ) as f:
    json.dump({'WANDB_RUN_ID': run_id}, f)
    bt.logging.success(f'Saved: {run_id} to file.')

# Start wandb run.
run_name = f'miner-{my_uid}-' + ''.join(random.choice( string.ascii_uppercase + string.digits ) for i in range(10))
config.uid = my_uid
config.hotkey = wallet.hotkey.ss58_address
config.run_name = run_name
config.version = pretrain.__version__
config.type = 'miner'
wandb_run = wandb.init(
    id = run_id,
    name = run_name,
    anonymous = "allow",
    project = pretrain.WANDB_PROJECT,
    entity = 'opentensor-dev',
    config = config,
    dir = config.full_path,
    allow_val_change=True,
)

# Signature
signature = wallet.hotkey.sign( wandb_run.id.encode() ).hex()
config.signature = signature
wandb.config.update( config, allow_val_change=True )
bt.logging.success(f'Successfully signed wandb run with signature {config.signature}')

# Save the model to wandb.
wandb.save( config.model_path )
bt.logging.success('Pushed artifact to the wandb run.')

# Start the training loop
epoch_step = 0
global_step = 0
n_acc_steps = 0
accumulation_steps = config.accumulation_steps  

try:
    while epoch_step < config.num_epochs or config.num_epochs == -1:
        # Initialize loss accumulator for the epoch
        epoch_loss = 0.0

        # Prepare the data loader with random pages for each epoch
        bt.logging.success( f"Loading {config.pages_per_epoch} pages for training this epoch" )
        random_pages = [random.randint(1, pretrain.dataset.SubsetFalconLoader.max_pages) for _ in range( config.pages_per_epoch )]
        loader = pretrain.dataset.SubsetFalconLoader(
            batch_size = config.bs, 
            sequence_length = config.sl, 
            pages = random_pages
        )

        # Enumerate over the data loader
        n_batches = 0
        optimizer.zero_grad()  # Initialize gradients to zero

        for i, batch in enumerate(loader):
            # Move the input batch to the device
            inputs = batch.to(model.device)
            
            # Forward pass: compute the model output and loss
            outputs = model(inputs, labels=inputs)

            loss = outputs.loss / accumulation_steps  # Scale loss
            loss.backward()  # Accumulate gradients

            if (i + 1) % accumulation_steps == 0:
                n_acc_steps += 1
                optimizer.step()  # Perform a single optimization step
                optimizer.zero_grad()  # Clear gradients
                bt.logging.success(f'Step: {n_acc_steps} loss: {outputs.loss.detach().item()}')
                wandb.log( { 'loss': outputs.loss.detach(), 'n_batches': n_batches }, step = n_acc_steps )

            torch.cuda.empty_cache()
                        
            # Log the loss for the current step
            n_batches += 1
            global_step += 1
            epoch_loss += outputs.loss.detach().item()

        # Calculate the average loss for the epoch
        avg_loss = epoch_loss / n_batches

        # Log the average loss for the epoch
        bt.logging.success(f'Epoch: {epoch_step} average loss: {avg_loss}')
        epoch_step += 1

        # Check if the average loss of this epoch is the best we've seen so far
        if avg_loss < best_avg_loss * ( 1 - pretrain.timestamp_epsilon ):
            best_avg_loss = avg_loss  # Update the best average loss
            bt.logging.success(f'New best average loss: {best_avg_loss}. Saving model...')
            
            # Save the model state to the specified path
            torch.save( model.state_dict(), config.model_path )

            # Save the new best model to wandb.
            wandb.save( config.model_path )
            bt.logging.success('Pushed the new artifact to the wandb run.')

finally: 
    wandb.finish()