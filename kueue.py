from typing import Optional, TypedDict

import pulumi
import pulumi_kubernetes as kubernetes
from pulumi import ResourceOptions


class KueueArgs(TypedDict):
    version: Optional[pulumi.Input[str]]
    """The version of the kueue system to deploy. Defaults to `v0.13.4`"""

    gpu_flavor: Optional[pulumi.Input[str]]
    """The GPU flavor for the kueue system. Defaults to `a100`"""

    total_gpus: pulumi.Input[int]
    """The total number of available GPUs"""


class Kueue(pulumi.ComponentResource):
    """
    This class sets up and configures a Kubernetes-based workload management system
    using Pulumi and the Kueue project. It assists in automating the creation of Kubernetes
    custom resources, deployments, and associated configurations for GPU-based training environments.

    The purpose of this class is to deploy and manage the necessary components such as Namespaces,
    Deployments, ResourceFlavors, ClusterQueues, and LocalQueues, which are
    essential for orchestrating GPU workloads in a Kubernetes cluster. By leveraging the
    Kueue project, it provides a robust solution for managing queued workloads efficiently,
    handling both scheduling and resource allocation.
    """

    def __init__(self,
                 name: str,
                 args: KueueArgs,
                 opts: Optional[ResourceOptions] = None) -> None:
        super().__init__('kueue-component:index:Kueue', name, {}, opts)

        namespace = "kueue-system"
        gpu_flavor = pulumi.Output.from_input(args.get("gpu_flavor") or "a100")
        version = pulumi.Output.from_input(args.get("version") or "v0.13.4")

        train_namespace = kubernetes.core.v1.Namespace(
            "train",
            metadata=kubernetes.meta.v1.ObjectMetaArgs(
                name="train"
            ),
            opts=pulumi.ResourceOptions(
                parent=self,
                provider=opts.provider
            )
        )

        kueue_release = kubernetes.yaml.v2.ConfigFile(
            "kueue",
            file=f"https://github.com/kubernetes-sigs/kueue/releases/download/{version}/manifests.yaml",
            opts=pulumi.ResourceOptions(
                parent=self,
                provider=opts.provider
            ),
        )

        kueue_controller_deployment = kubernetes.apps.v1.Deployment.get(
            "kueue-controller-deployment",
            f"{namespace}/kueue-controller-manager",
            opts=pulumi.ResourceOptions(
                parent=self,
                provider=opts.provider,
                depends_on=[kueue_release]
            )
        )

        # Create ResourceFlavor for the selected GPU type
        resource_flavor = kubernetes.apiextensions.CustomResource(
            f"{gpu_flavor}-gpu-flavor",
            api_version="kueue.x-k8s.io/v1beta1",
            kind="ResourceFlavor",
            metadata=kubernetes.meta.v1.ObjectMetaArgs(
                name=f"{gpu_flavor}-gpu"
            ),
            spec={
                "nodeLabels": {
                    "purpose": "training",
                    "gpu-type": f"{gpu_flavor}"
                },
                "tolerations": [
                    {
                        "key": "nvidia.com/gpu",
                        "operator": "Equal",
                        "value": "present",
                        "effect": "NoSchedule"
                    }
                ]
            },
            opts=pulumi.ResourceOptions(
                parent=self,
                provider=opts.provider,
                depends_on=[kueue_release],
                delete_before_replace=True
            )
        )

        # Create ClusterQueue for training workloads
        training_cluster_queue = kubernetes.apiextensions.CustomResource(
            f"training-{gpu_flavor}-cq",
            api_version="kueue.x-k8s.io/v1beta1",
            kind="ClusterQueue",
            metadata=kubernetes.meta.v1.ObjectMetaArgs(
                name=f"training-{gpu_flavor}"
            ),
            spec={
                "namespaceSelector": {},
                "resourceGroups": [
                    {
                        "coveredResources": ["nvidia.com/gpu"],
                        "flavors": [
                            {
                                "name": f"{gpu_flavor}-gpu",
                                "resources": [
                                    {
                                        "name": "nvidia.com/gpu",
                                        "nominalQuota": args["total_gpus"],
                                    }
                                ]
                            }
                        ]
                    }
                ],
                "queueingStrategy": "BestEffortFIFO"
            },
            opts=pulumi.ResourceOptions(
                parent=self,
                provider=opts.provider,
                depends_on=[resource_flavor],
                delete_before_replace=True
            )
        )

        # Create LocalQueue in train namespace
        training_local_queue = kubernetes.apiextensions.CustomResource(
            "pq-train-lq",
            api_version="kueue.x-k8s.io/v1beta1",
            kind="LocalQueue",
            metadata=kubernetes.meta.v1.ObjectMetaArgs(
                name="pq-train",
                namespace="train"
            ),
            spec={
                "clusterQueue": f"training-{gpu_flavor}"
            },
            opts=pulumi.ResourceOptions(
                parent=self,
                provider=opts.provider,
                depends_on=[train_namespace, training_cluster_queue],
                delete_before_replace=True
            )
        )

        self.register_outputs({})
