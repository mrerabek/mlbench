from rest_framework.viewsets import ViewSet
from rest_framework.response import Response
from rest_framework import status
from api.models import KubePod, KubeMetric
from api.serializers import KubePodSerializer

from kubernetes import client, config
import kubernetes.stream as stream

import os
from itertools import groupby
from datetime import datetime
import pytz


class KubePodView(ViewSet):
    """Handles the /api/pods endpoint
    """

    serializer_class = KubePodSerializer

    def list(self, request, format=None):
        pod = KubePod.objects.all()

        serializer = KubePodSerializer(pod, many=True)
        return Response(serializer.data)


class KubeMetricsView(ViewSet):
    """Handles the /api/metrics endpoint
    """

    def list(self, request, format=None):
        """Get all metrics

        Arguments:
            request {[Django request]} -- The request object

        Keyword Arguments:
            format {string} -- Output format to use (default: {None})

        Returns:
            Json -- Object containing all metrics
        """

        result = {pod.name: {
            g[0]: [
                {'date': e.date, 'value': e.value}
                for e in sorted(g[1], key=lambda x: x.date)
            ] for g in groupby(
                sorted(pod.metrics.all(), key=lambda m: m.name),
                key=lambda m: m.name)
        } for pod in KubePod.objects.all()}

        return Response(result, status=status.HTTP_200_OK)

    def retrieve(self, request, pk=None, format=None):
        """Get all metrics for a pod

        Arguments:
            request {[Django request]} -- The request object

        Keyword Arguments:
            pk {string} -- Name of the pod
            format {string} -- Output format to use (default: {None})

        Returns:
            Json -- Object containing all metrics for the pod
        """
        since = self.request.query_params.get('since', None)

        if since is not None:
            since = datetime.strptime(since, "%Y-%m-%dT%H:%M:%S.%fZ")
            since = pytz.utc.localize(since)

        pod = KubePod.objects.filter(name=pk).first()

        result = {
            g[0]: [
                {'date': e.date, 'value': e.value}
                for e in sorted(g[1], key=lambda x: x.date)
                if since is None or e.date > since
            ] for g in groupby(
                sorted(pod.metrics.all(), key=lambda m: m.name),
                key=lambda m: m.name)
        }

        return Response(result, status=status.HTTP_200_OK)

    def create(self, request):
        """Create a new metric

        Arguments:
            request {[Django request]} -- The request object

        Returns:
            Json -- Returns posted values
        """

        d = request.data
        pod = KubePod.objects.filter(name=d['pod_name']).first()

        if pod is None:
            return Response({
                'status': 'Not Found',
                'message': 'Pod not found'
            }, status=status.HTTP_404_NOT_FOUND)

        metric = KubeMetric(
            name=d['name'],
            date=d['date'],
            value=d['value'],
            metadata=d['metadata'],
            pod=pod)
        metric.save()

        return Response(
            metric, status=status.HTTP_201_CREATED
        )


class MPIJobView(ViewSet):
    """Handles the /api/mpi_jobs endpoint
    """

    def create(self, request):
        config.load_incluster_config()

        v1 = client.CoreV1Api()

        release_name = os.environ.get('MLBENCH_KUBE_RELEASENAME')
        ns = os.environ.get('MLBENCH_NAMESPACE')

        ret = v1.list_namespaced_pod(
            ns,
            label_selector="component=worker,app=mlbench,release={}"
            .format(release_name))

        result = {'pods': []}
        hosts = []
        for i in ret.items:
            result['pods'].append((i.status.pod_ip,
                                   i.metadata.namespace,
                                   i.metadata.name,
                                   str(i.metadata.labels)))
            hosts.append("{}.{}".format(i.metadata.name, release_name))

        # exec_command = [
        #     '/.openmpi/bin/mpirun',
        #     '--host', ",".join(hosts),
        #     '/conda/bin/python', '/app/main.py', 'test_synchronize_sgd']

        # exec_command = [
        #     '/.openmpi/bin/mpirun',
        #     '--host', ",".join(hosts),
        #     '/conda/bin/python', '/app/sgd-mnist.py', "--epochs", "1",
        #     "--batch-size", "128", "--datafolder", "/datasets/torch/mnist/"]

        exec_command = [
            '/.openmpi/bin/mpirun',
            "--mca", "btl_tcp_if_exclude", "docker0,lo",
            '--host', ",".join(hosts),
            '/conda/bin/python', "/codes/main.py",
        ]

        result['command'] = str(exec_command)

        name = ret.items[0].metadata.name

        result['master_name'] = name

        resp = stream.stream(v1.connect_get_namespaced_pod_exec, name,
                             'default',
                             command=exec_command,
                             stderr=True, stdin=False,
                             stdout=True, tty=False)

        result["response"] = resp
        return Response(result, status=status.HTTP_201_CREATED)
