#!/bin/bash
cd /root/vesta
source /root/vesta/.venv/bin/activate
python cluster.py --shards-per-cluster 5 --num-clusters 3