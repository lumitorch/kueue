from pulumi.provider.experimental import component_provider_host
from kueue import KueueStack

if __name__ == "__main__":
    component_provider_host(name="kueue-component", components=[KueueStack])
