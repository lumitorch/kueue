from typing import Optional, TypedDict, TypeVar, Any

import pulumi
import pulumi_kubernetes as kubernetes
from pulumi import ResourceOptions

T = TypeVar("T")


# Normalize Input[T] to Output[T] and apply a default when the value is None
# Avoids using Python's `or`, which would clobber valid falsy values like 0 or "".
def with_default(value: Optional[pulumi.Input[T]], default: T) -> pulumi.Output[T]:
    return pulumi.Output.from_input(value).apply(lambda v: default if v is None else v)


# ---- Input validators / coercers -------------------------------------------
# Ensures we always have an Output[int] and fails fast with a helpful message
# if the user passes an invalid value (e.g., "four").

def _coerce_int(x: Any, *, name: str, min_: int | None = None, max_: int | None = None) -> int:
    if isinstance(x, bool):
        raise TypeError(f"{name} must be an integer, not bool")
    if isinstance(x, int):
        n = x
    elif isinstance(x, float) and x.is_integer():
        n = int(x)
    elif isinstance(x, str):
        s = x.strip()
        try:
            n = int(s, 10)
        except ValueError:
            raise TypeError(f"{name} must be an integer (got {x!r})")
    elif x is None:
        raise ValueError(f"{name} is required")
    else:
        raise TypeError(f"{name} must be an integer (got {type(x).__name__})")

    if min_ is not None and n < min_:
        raise ValueError(f"{name} must be ≥ {min_} (got {n})")
    if max_ is not None and n > max_:
        raise ValueError(f"{name} must be ≤ {max_} (got {n})")
    return n


def as_int(value: Optional[pulumi.Input[Any]], *, default: int | None, name: str, min_: int | None = None, max_: int | None = None) -> \
pulumi.Output[int]:
    # Normalize to Output, apply default if None, then validate/convert to int
    return pulumi.Output.from_input(value).apply(
        lambda v: _coerce_int(default if v is None else v, name=name, min_=min_, max_=max_)
    )


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
        gpu_flavor = with_default(args.get("gpu_flavor").lower(), "a100")
        version = with_default(args.get("version"), "v0.13.4")
        total_gpus = as_int(args.get("total_gpus"), default=None, name="total_gpus", min_=1)

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

        kueue_namespace = kubernetes.core.v1.Namespace(
            namespace,
            metadata=kubernetes.meta.v1.ObjectMetaArgs(
                name=namespace
            ),
            opts=pulumi.ResourceOptions(
                parent=self,
                provider=opts.provider
            )
        )

        kueue_release = kubernetes.helm.v3.Release(
            "kueue",
            name="kueue",
            chart="oci://registry.k8s.io/kueue/charts/kueue",
            version=version.apply(lambda v: v.removeprefix("v")),
            namespace=kueue_namespace.metadata.name,
            opts=pulumi.ResourceOptions(
                parent=self,
                provider=opts.provider
            )
        )

        kueue_controller_deployment = kubernetes.apps.v1.Deployment.get(
            "kueue-controller-deployment",
            # Pass the id through the release status to ensure this only runs after the release is ready
            kueue_release.status.apply(lambda _: f"{namespace}/kueue-controller-manager"),
            opts=pulumi.ResourceOptions(
                parent=self,
                provider=opts.provider,
                depends_on=[kueue_release]
            )
        )

        # Create ResourceFlavor for the selected GPU type
        resource_flavor = kubernetes.apiextensions.CustomResource(
            "gpu-flavor",
            api_version="kueue.x-k8s.io/v1beta1",
            kind="ResourceFlavor",
            metadata=kubernetes.meta.v1.ObjectMetaArgs(
                name=pulumi.Output.format("{}-gpu", gpu_flavor)
            ),
            spec={
                "nodeLabels": {
                    "purpose": "training",
                    "gpu-type": gpu_flavor
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
            "training-cq",
            api_version="kueue.x-k8s.io/v1beta1",
            kind="ClusterQueue",
            metadata=kubernetes.meta.v1.ObjectMetaArgs(
                name=pulumi.Output.format("training-{}", gpu_flavor)
            ),
            spec={
                "namespaceSelector": {},
                "resourceGroups": [
                    {
                        "coveredResources": ["nvidia.com/gpu"],
                        "flavors": [
                            {
                                "name": pulumi.Output.format("{}-gpu", gpu_flavor),
                                "resources": [
                                    {
                                        "name": "nvidia.com/gpu",
                                        "nominalQuota": total_gpus,
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
                "clusterQueue": pulumi.Output.format("training-{}", gpu_flavor)
            },
            opts=pulumi.ResourceOptions(
                parent=self,
                provider=opts.provider,
                depends_on=[train_namespace, training_cluster_queue],
                delete_before_replace=True
            )
        )

        self.register_outputs({
            "train_namespace": train_namespace,
            "kueue_namespace": kueue_namespace,
            "kueue_release": kueue_release,
            "kueue_controller": kueue_controller_deployment,
            "resource_flavor": resource_flavor,
            "training_cluster_queue": training_cluster_queue,
            "training_local_queue": training_local_queue,
        })
