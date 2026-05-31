# CUDA_VISIBLE_DEVICES=6 \
# nohup python /mnt/linjienas/xk/Gastritis_FM/DINOv3_custom_training-main/scripts/train.py \
#     --config /mnt/linjienas/xk/Gastritis_FM/DINOv3_custom_training-main/configs/industrial_ssl.yaml > /mnt/linjienas/xk/Gastritis_FM/DINOv3_custom_training-main/outputs/logs/sft_dinov3_bs64.log 2>&1 &

CUDA_VISIBLE_DEVICES=0 python /mnt/linjienas/xk/Gastritis_FM/DINOv3_custom_training-main/scripts/train_kun.py \
    --config /mnt/linjienas/xk/Gastritis_FM/DINOv3_custom_training-main/configs/industrial_ssl.yaml > /mnt/linjienas/xk/Gastritis_FM/DINOv3_custom_training-main/outputs/logs/Gastro_Endo/sft_dinov3_bs128.log 2>&1 &