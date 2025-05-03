# AI_waitress
### Replicate the Conda Environment

```bash

## Step 1::

# 1. Clone the repo and cd in
git clone https://github.com/vvikasreddy/AI_waitress.git
cd AI_waitress

# 2. Create & activate the Conda env (named “verbi” per environment.yml)
conda env create -f environment.yml
conda activate ai_waitress

# 3. (Optional) If you also maintain a requirements.txt for pure-pip installs:
pip install -r requirements.txt


## Step 2::
## Quick Start: Run Restaurant & Customer

Open **two** Command Prompt windows and in each one run the following:

1. **Window 1 – Restaurant Backend**  
   ```bat
   conda activate ai_waitress
   python main.py
2. **Window 2 – Customer Simulation**  
    ```bat
    conda activate ai_waitress
    python customer.py
    ```

