# Lint as: python2, python3
# Copyright 2020 Google LLC. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Tests for tfx.experimental.templates.taxi.e2e_test.kubeflow_e2e."""

# TODO(b/149535307): Remove __future__ imports
from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import os
import subprocess
import urllib.request

from absl import logging
import kfp
import kfp_server_api
import tensorflow as tf

from tfx.experimental.templates.taxi.e2e_tests import test_utils
from tfx.orchestration import test_utils as orchestration_test_utils


class TaxiTemplateKubeflowE2ETest(test_utils.BaseEndToEndTest):

  def setUp(self):
    super(TaxiTemplateKubeflowE2ETest, self).setUp()

    self._pipeline_name = ('taxi-template-kubeflow-e2e-test-' +
                           orchestration_test_utils.random_id())
    logging.info('Pipeline: %s', self._pipeline_name)
    self._endpoint = self._get_endpoint()
    logging.info('ENDPOINT: %s', self._endpoint)

    self._gcp_project_id = 'tfx-oss-testing'
    self._target_container_image = 'gcr.io/{}/{}'.format(
        self._gcp_project_id, self._pipeline_name)

    self._prepare_skaffold()

  def tearDown(self):
    super(TaxiTemplateKubeflowE2ETest, self).tearDown()
    try:
      self._cleanup_kfp()
    except (kfp_server_api.rest.ApiException, AttributeError) as err:
      logging.info(err)

  def _cleanup_kfp(self):
    self._delete_runs()
    self._delete_pipeline()
    self._delete_pipeline_output()
    self._delete_container_image()

  def _delete_runs(self):
    kfp_client = kfp.Client(host=self._endpoint)
    experiment_id = kfp_client.get_experiment(
        experiment_name=self._pipeline_name).id
    response = kfp_client.list_runs(experiment_id=experiment_id)
    for run in response.runs:
      kfp_client._run_api.delete_run(id=run.id)

  def _delete_pipeline(self):
    self._runCli([
        'pipeline', 'delete', '--engine', 'kubeflow', '--pipeline_name',
        self._pipeline_name
    ])

  def _delete_pipeline_output(self):
    bucket_name = self._gcp_project_id + '-kubeflowpipelines-default'
    path = 'tfx_pipeline_output/{}'.format(self._pipeline_name)
    orchestration_test_utils.delete_gcs_files(self._gcp_project_id, bucket_name,
                                              path)

  def _delete_container_image(self):
    subprocess.run([  # pylint: disable=subprocess-run-check
        'gcloud', 'container', 'images', 'delete', self._target_container_image
    ])

  def _get_endpoint(self):
    output = subprocess.check_output(
        'kubectl describe configmap inverse-proxy-config -n kubeflow'.split())
    for line in output.decode('utf-8').split('\n'):
      if line.endswith('googleusercontent.com'):
        return line

  def _prepare_skaffold(self):
    self._skaffold = os.path.join(self._temp_dir, 'skaffold')
    urllib.request.urlretrieve(
        'https://storage.googleapis.com/skaffold/releases/latest/skaffold-linux-amd64',
        self._skaffold)
    os.chmod(self._skaffold, 0o775)

  def testPipeline(self):
    self._copyTemplate()
    os.environ['KUBEFLOW_HOME'] = os.path.join(self._temp_dir, 'kubeflow')

    # Create a pipeline with only one component.
    result = self._runCli([
        'pipeline',
        'create',
        '--engine',
        'kubeflow',
        '--pipeline_path',
        'kubeflow_dag_runner.py',
        '--endpoint',
        self._endpoint,
        '--build-target-image',
        self._target_container_image,
        '--skaffold-cmd',
        self._skaffold,
        '--build-base-image',
        'tensorflow/tfx:latest',
    ])
    self.assertEqual(0, result.exit_code)
    self.assertIn(
        'Pipeline "{}" created successfully.'.format(self._pipeline_name),
        result.output)

    # Run the pipeline.
    result = self._runCli([
        'run',
        'create',
        '--engine',
        'kubeflow',
        '--pipeline_name',
        self._pipeline_name,
        '--endpoint',
        self._endpoint,
    ])
    self.assertEqual(0, result.exit_code)

    # Update the pipeline to include all components.
    updated_pipeline_file = self._addAllComponents()
    logging.info('Updated %s to add all components to the pipeline.',
                 updated_pipeline_file)
    result = self._runCli([
        'pipeline',
        'update',
        '--engine',
        'kubeflow',
        '--pipeline_path',
        'kubeflow_dag_runner.py',
        '--endpoint',
        self._endpoint,
        '--skaffold-cmd',
        self._skaffold,
    ])
    self.assertEqual(0, result.exit_code)
    self.assertIn(
        'Pipeline "{}" updated successfully.'.format(self._pipeline_name),
        result.output)

    # Run the updated pipeline.
    result = self._runCli([
        'run',
        'create',
        '--engine',
        'kubeflow',
        '--pipeline_name',
        self._pipeline_name,
        '--endpoint',
        self._endpoint,
    ])
    self.assertEqual(0, result.exit_code)


if __name__ == '__main__':
  tf.test.main()
