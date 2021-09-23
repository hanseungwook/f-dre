#!/bin/bash

for i in 1 2
do
    python3 main.py --classify --config classification/mi/joint_flow_z_mi20_mu0.yaml  --exp_id mi20_mu0_${i} --ni --mi --seed ${i} > mi20_mu0_run${i}.txt 2>&1 
    python3 main.py --classify --config classification/mi/joint_flow_z_mi20_mu-1_1.yaml  --exp_id mi20_mu-1_1_${i} --ni --mi --seed ${i} > mi20_mu-1_1_run${i}.txt 2>&1 
    python3 main.py --classify --config classification/mi/joint_flow_z_mi40_mu0.yaml  --exp_id mi40_mu0_${i} --ni --mi --seed ${i} > mi40_mu0_run${i}.txt 2>&1 
    python3 main.py --classify --config classification/mi/joint_flow_z_mi40_mu-0.5_0.6.yaml  --exp_id mi40_mu-0.5_0.6_${i} --ni --mi --seed ${i} > mi40_mu-0.5_0.6_run${i}.txt 2>&1
    python3 main.py --classify --config classification/mi/joint_flow_z_mi80_mu0.yaml  --exp_id mi80_mu0_${i} --ni --mi --seed ${i} > mi80_mu0_run${i}.txt 2>&1
    python3 main.py --classify --config classification/mi/joint_flow_z_mi80_mu-0.5_0.5.yaml  --exp_id mi80_mu-0.5_0.5_${i} --ni --mi --seed ${i} > mi80_mu-0.5_0.5_run${i}.txt 2>&1
done
    
