#!/bin/bash

# Load common configuration
SHELL_PATH=$(dirname "$0")
source "$SHELL_PATH/glasses_config.sh"

#scp sdk_global.json to x1 
echo "scp sdk_global.json"
sshpass -p "$PASSWORD" scp $SSH_PARAM -r $SHELL_PATH/sdk_global_send_data_3dof.json $GLASSES_IP:/usrdata/pilot/conf/sdk_global.json







