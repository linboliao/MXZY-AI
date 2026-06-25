# MXZY-AI

Code repository for the study:

**Toward Stable and Clinically Deployable AI for Histopathologic Diagnosis of Prostate Cancer**

This repository provides the main implementation used for whole-slide image (WSI)-level prostate cancer diagnosis, pathology foundation model feature extraction, multiple-instance learning (MIL)-based classification, and auxiliary lesion localization.

The code is intended to support reproducibility of the computational workflow described in the manuscript. Because the original clinical WSIs contain sensitive patient information, the raw datasets are not publicly distributed in this repository.

---

## Overview

MXZY-AI implements a computational pathology pipeline for prostate cancer diagnosis from H&E-stained whole-slide images. The workflow includes:

1. WSI preprocessing and tissue patch coordinate generation.
2. Patch-level feature extraction using pathology foundation models.
3. Slide-level diagnosis using MIL-based classifiers.
4. Cross-fold model inference and prediction aggregation.
5. Auxiliary cancer localization using a YOLO-based detection module.
6. Generation of slide-level diagnostic output files and region-level GeoJSON localization results.

The framework was designed for stable and efficient prostate cancer diagnosis across heterogeneous pathology settings, including different specimen types, staining conditions, and external validation centers.

---

## Repository Structure

```text
MXZY-AI/
├── MIL_BASELINE/                 # MIL framework for WSI-level classification
│   ├── configs/                  # YAML configuration files for MIL models
│   ├── datasets/                 # Dataset CSV templates
│   ├── feature_extractor/        # Feature extraction modules
│   ├── modules/                  # MIL model implementations
│   ├── process/                  # Training and testing pipelines
│   ├── split_scripts/            # Dataset split utilities
│   ├── train_mil.py              # MIL training entry
│   ├── test_mil.py               # MIL testing entry
│   └── infer_mil.py              # MIL inference entry
│
├── PrePATH/                      # WSI preprocessing and patch extraction utilities
├── ultralytics/                  # YOLO-based lesion localization module
├── run_medical_image_pipeline.py # Main integrated diagnostic pipeline
├── runs.py                       # Alternative simplified pipeline script
├── args.txt                      # Example WSI preprocessing arguments
└── patch_params.txt              # Example patch extraction parameters
```

---

## Main Pipeline

The integrated pipeline performs the following steps:

```text
Input WSIs
   ↓
Tissue segmentation and patch coordinate generation
   ↓
Pathology foundation model feature extraction
   ↓
MIL-based WSI diagnosis
   ↓
Cross-fold prediction aggregation
   ↓
YOLO-based lesion localization
   ↓
Slide-level diagnosis and GeoJSON output
```

The main entry script is:

```bash
python run_medical_image_pipeline.py \
    --wsi_dir /path/to/wsi_dir \
    --output_dir /path/to/output_dir \
    --wsi_format svs \
    --model h-optimus-1 \
    --normal True
```

For selected slides only, use semicolon-separated filenames:

```bash
python run_medical_image_pipeline.py \
    --wsi_dir /path/to/wsi_dir \
    --slide_list slide_001.svs;slide_002.svs \
    --output_dir /path/to/output_dir \
    --wsi_format svs \
    --model h-optimus-1 \
    --normal True
```

---

## Input Data Format

### Whole-slide images

The pipeline expects a directory containing WSI files. Supported formats depend on the local OpenSlide and preprocessing environment. Commonly used formats include:

```text
.svs
.ndpi
.tif
.tiff
.mrxs
.kfb
```

### MIL feature CSV

For MIL inference, the test CSV should contain at least:

```text
test_slide_path
```

When ground-truth labels are available for evaluation, an additional label column can be provided:

```text
test_slide_path,test_label
/path/to/features/slide_001.pt,0
/path/to/features/slide_002.pt,1
```

Here, `0` and `1` denote benign and malignant classes, respectively, unless otherwise specified in the corresponding configuration file.

---

## Output Files

After successful execution, the output directory may contain:

```text
output_dir/
├── patches_cls/                  # Patch coordinates for classification
├── feat_cls/                     # Extracted patch-level features
├── cancer/                       # Cancer diagnosis results
│   ├── 0/                        # Fold-specific inference result
│   ├── 1/
│   ├── 2/
│   ├── 3/
│   ├── 4/
│   └── merged_voting_result.csv  # Aggregated WSI-level cancer diagnosis
├── gleason/                      # Gleason pattern inference results
├── isup/                         # ISUP grade inference results, if enabled
├── yolo/                         # YOLO-based localization results
├── *.geojson                     # Region-level lesion localization files
└── exist_cancer.json             # Slide-level summary file
```

The `merged_voting_result.csv` file contains the aggregated slide-level prediction and fold-level voting information.

---

## Installation

We recommend creating a dedicated Python environment.

```bash
conda create -n mxzy-ai python=3.8 -y
conda activate mxzy-ai
```

Install the core dependencies according to your local CUDA, PyTorch, OpenSlide, and pathology foundation model environment.

A typical environment requires:

```bash
pip install numpy pandas scikit-learn tqdm pyyaml
pip install openslide-python geopandas shapely
pip install torch torchvision
```

For WSI reading, OpenSlide must also be installed at the system level.

For YOLO-based localization, install the required dependencies under the `ultralytics` module according to the local implementation.

---

## Pretrained Models and Checkpoints

This repository contains code for running the diagnostic pipeline. Large pretrained weights, private model checkpoints, and clinical WSI data may not be included due to storage size, licensing restrictions, or patient privacy considerations.

Users should prepare the required checkpoints before running inference, including:

```text
MIL_BASELINE/ckpts/
ultralytics/runs/detect/
```

The expected checkpoint paths should match the paths defined in the pipeline scripts or be manually updated before execution.

---

## MIL Training and Testing

The MIL module can also be used independently.

### Training

```bash
cd MIL_BASELINE

python train_mil.py \
    --yaml_path configs/cancer/CLAM_MB_MIL-h-optimus-1.yaml
```

Dynamic configuration overrides are supported:

```bash
python train_mil.py \
    --yaml_path configs/cancer/CLAM_MB_MIL-h-optimus-1.yaml \
    --options General.seed=2024 General.num_epochs=50 Model.in_dim=1536
```

### Testing / Inference

```bash
python test_mil.py \
    --yaml_path configs/cancer/CLAM_MB_MIL-h-optimus-1.yaml \
    --test_dataset_csv /path/to/test.csv \
    --model_weight_path /path/to/model_weight.pth \
    --test_log_dir /path/to/test_logs
```

For inference without full evaluation labels, make sure the input CSV contains the feature path column required by the corresponding script.

---

## Data Availability

The clinical whole-slide images used in the study are not publicly released because they contain sensitive patient-related information and are subject to institutional ethics, privacy, and data-use restrictions.

De-identified derived data or processed features may be made available from the corresponding author upon reasonable request, subject to institutional approval and data-sharing agreements.

---

## Code Availability

This repository provides the implementation of the main computational pipeline used in the manuscript. The code is released for academic and research use.

Users should carefully check local paths, checkpoint locations, WSI formats, and environment dependencies before running the pipeline.

---

## Clinical Use Disclaimer

This software is intended for research use only. It is not approved for clinical diagnosis, treatment decision-making, or direct patient management.

Any clinical application requires independent validation, regulatory review, and approval according to local laws and institutional requirements.

---

## Citation

If you use this repository, please cite the associated manuscript:

```bibtex
@article{liao2026stable_prostate_ai,
  title   = {Toward Stable and Clinically Deployable AI for Histopathologic Diagnosis of Prostate Cancer},
  author  = {Liao, Linbo and others},
  journal = {Cell Reports Medicine},
  year    = {2026},
  note    = {Manuscript under review}
}
```

Please update the citation information after publication.

---

## Contact

For questions about the code or manuscript, please contact the corresponding author or open an issue in this repository.
