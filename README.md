# Kueue Pulumi Component

A Pulumi component for deploying [Kueue](https://kueue.sigs.k8s.io/) (Kubernetes job queueing system) with GPU resource management capabilities.

## Overview

This component provides a simple way to deploy Kueue on your Kubernetes cluster with pre-configured GPU resource management. Kueue is a Kubernetes-native system that manages quotas and how jobs consume them, providing job queueing with support for resource quotas and prioritization.

## Features

- **Automated Kueue Deployment**: Deploys Kueue from official releases
- **GPU Resource Management**: Pre-configured ResourceFlavor for GPU types (default: A100)
- **Training Workload Support**: Creates ClusterQueue and LocalQueue for training workloads
- **Flexible Configuration**: Configurable GPU flavor and total GPU count
- **Kubernetes Native**: Uses Kubernetes Custom Resources for queue management

## Architecture

The component creates the following resources:

1. **Kueue System**: Deploys the Kueue controller and CRDs
2. **ResourceFlavor**: Defines GPU resource characteristics and node selection
3. **ClusterQueue**: Manages resource quotas at the cluster level
4. **LocalQueue**: Provides namespace-level queue management in the `train` namespace

## Requirements

- Kubernetes cluster
- Pulumi CLI
- Python 3.7+
- GPU-enabled nodes (for GPU workloads)

## Installation

### Prerequisites

Ensure you have the required dependencies:

```bash
pip install pulumi>=3.0.0,<4.0.0 pulumi-kubernetes>=4.0.0,<5.0.0
```

### Usage

```python
from kueue import Kueue

# Basic usage with default A100 GPUs
kueue = Kueue("my-kueue", {
    "total_gpus": 8  # Required: specify total available GPUs
})

# Custom configuration
kueue = Kueue("my-kueue", {
    "version": "v0.13.4",  # Optional: Kueue version (default: v0.13.4)
    "gpu_flavor": "v100",  # Optional: GPU type (default: a100)
    "total_gpus": 16  # Required: total available GPUs
})
```

## Configuration

### KueueArgs

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `total_gpus` | `int` | Yes | - | Total number of available GPUs in the cluster |
| `version` | `str` | No | `v0.13.4` | Kueue version to deploy |
| `gpu_flavor` | `str` | No | `a100` | GPU flavor/type for resource management |

### Supported GPU Flavors

The component supports various GPU flavors. Common examples:
- `a100` (default)
- `v100`
- `t4`
- `h100`

The GPU flavor is used for:
- Resource flavor naming
- Node label matching (`gpu-type: <flavor>`)
- Queue naming

## Resource Management

### ResourceFlavor

The component creates a ResourceFlavor with:
- Node labels for GPU type selection
- Tolerations for GPU nodes
- Purpose labeling for training workloads

### ClusterQueue

Features:
- Covers `nvidia.com/gpu` resources
- Uses BestEffortFIFO queueing strategy
- Namespace selector allows all namespaces
- Configurable GPU quota based on `total_gpus`

### LocalQueue

- Created in the `train` namespace
- Named `pq-train`
- Connects to the training ClusterQueue

## Example: Complete Deployment

```python
import pulumi
import pulumi_kubernetes as k8s
from kueue import Kueue

# Create namespace for training workloads
train_namespace = k8s.core.v1.Namespace(
    "train-namespace",
    metadata=k8s.meta.v1.ObjectMetaArgs(name="train")
)

# Deploy Kueue with 8 A100 GPUs
kueue = Kueue("kueue-system", {
    "version": "v0.13.4",
    "gpu_flavor": "a100",
    "total_gpus": 8
})

# Example PyTorchJob that uses the queue
pytorch_job = k8s.apiextensions.CustomResource(
    "example-pytorch-job",
    api_version="kubeflow.org/v1",
    kind="PyTorchJob",
    metadata=k8s.meta.v1.ObjectMetaArgs(
        name="pytorch-example",
        namespace="train",
        labels={"kueue.x-k8s.io/queue-name": "pq-train"}  # Use the LocalQueue
    ),
    spec={
        "pytorchReplicaSpecs": {
            "Master": {
                "replicas": 1,
                "template": {
                    "spec": {
                        "containers": [{
                            "name": "pytorch",
                            "image": "pytorch/pytorch:latest",
                            "resources": {
                                "limits": {"nvidia.com/gpu": 1}
                            }
                        }]
                    }
                }
            }
        }
    },
    opts=pulumi.ResourceOptions(depends_on=[kueue, train_namespace])
)
```

## Monitoring and Management

After deployment, you can monitor queues using `kubectl`:

```bash
# Check ClusterQueues
kubectl get clusterqueues

# Check LocalQueues
kubectl get localqueues -n train

# Check ResourceFlavors
kubectl get resourceflavors

# Monitor workloads
kubectl get workloads -A
```

## Troubleshooting

### Common Issues

1. **Pods not scheduling**: Ensure your nodes have the correct GPU labels and taints
2. **Queue not found**: Verify the LocalQueue exists in the correct namespace
3. **Resource limits**: Check that your total_gpus matches available cluster resources

### Verification

Check that Kueue is running:

```bash
kubectl get pods -n kueue-system
kubectl get crd | grep kueue
```

## Version Compatibility

- Kueue: v0.13.4 (configurable)
- Kubernetes: 1.22+
- Pulumi: 3.0+
- Pulumi Kubernetes Provider: 4.0+

## Contributing

This component is part of the LumiTorch infrastructure toolkit. For issues and contributions, please refer to the project repository.

## License

Please refer to the project's license file for licensing information.
