from pulumi.provider.experimental import component_provider_host
from kueue import Kueue

if __name__ == "__main__":
    component_provider_host(name="kueue-component", components=[Kueue])
