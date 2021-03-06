#!/usr/bin/env
# Copyright 2014 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"). You
# may not use this file except in compliance with the License. A copy of
# the License is located at
#
# http://aws.amazon.com/apache2.0/
#
# or in the "license" file accompanying this file. This file is
# distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF
# ANY KIND, either express or implied. See the License for the specific
# language governing permissions and limitations under the License.
from tests import unittest
import mock

import botocore
from botocore import client
from botocore import hooks
from botocore.credentials import Credentials
from botocore.exceptions import ParamValidationError
from botocore import exceptions


class TestAutoGeneratedClient(unittest.TestCase):
    def setUp(self):
        self.service_description = {
            'metadata': {
                'apiVersion': '2014-01-01',
                'endpointPrefix': 'myservice',
                'signatureVersion': 'v4',
                'protocol': 'query'
            },
            'operations': {
                'TestOperation': {
                    'name': 'TestOperation',
                    'http': {
                        'method': 'POST',
                        'requestUri': '/',
                    },
                    'input': {'shape': 'TestOperationRequest'},
                }
            },
            'shapes': {
                'TestOperationRequest': {
                    'type': 'structure',
                    'required': ['Foo'],
                    'members': {
                        'Foo': {'shape': 'StringType'},
                        'Bar': {'shape': 'StringType'},
                    }
                },
                'StringType': {'type': 'string'}
            }
        }
        self.loader = mock.Mock()
        self.loader.load_service_model.return_value = self.service_description
        self.credentials = Credentials('access-key', 'secret-key')

        self.endpoint_creator_patch = mock.patch('botocore.client.EndpointCreator')
        self.endpoint_creator_cls = self.endpoint_creator_patch.start()
        self.endpoint_creator = self.endpoint_creator_cls.return_value

        self.endpoint = mock.Mock()
        self.endpoint.make_request.return_value = (mock.Mock(status_code=200), {})
        self.endpoint_creator.create_endpoint.return_value = self.endpoint

    def tearDown(self):
        self.endpoint_creator_patch.stop()

    def create_client_creator(self, endpoint_creator=None, event_emitter=None,
                              response_parser_factory=None):
        if event_emitter is None:
            event_emitter = hooks.HierarchicalEmitter()
        endpoint_resolver = mock.Mock()
        endpoint_resolver.construct_endpoint.return_value = {
            'properties': {},
            'uri': 'http://foo'
        }

        if endpoint_creator is not None:
            self.endpoint_creator_cls.return_value = endpoint_creator
        creator = client.ClientCreator(
            self.loader, endpoint_resolver, 'user-agent', event_emitter,
            response_parser_factory)
        return creator

    def test_client_generated_from_model(self):
        creator = self.create_client_creator()
        service_client = creator.create_client(
            'myservice', 'us-west-2', credentials=self.credentials)
        self.assertTrue(hasattr(service_client, 'test_operation'))

    @mock.patch('botocore.client.RequestSigner')
    def test_client_signature_no_override(self, request_signer):
        creator = self.create_client_creator()
        service_client = creator.create_client(
            'myservice', 'us-west-2', credentials=self.credentials,
            scoped_config={})
        request_signer.assert_called_with(
            mock.ANY, mock.ANY, mock.ANY, 'v4', mock.ANY, mock.ANY)

    @mock.patch('botocore.client.RequestSigner')
    def test_client_signature_override_config_file(self, request_signer):
        creator = self.create_client_creator()
        config = {
            'myservice': {'signature_version': 'foo'}
        }
        service_client = creator.create_client(
            'myservice', 'us-west-2', credentials=self.credentials,
            scoped_config=config)
        request_signer.assert_called_with(
            mock.ANY, mock.ANY, mock.ANY, 'foo', mock.ANY, mock.ANY)

    @mock.patch('botocore.client.RequestSigner')
    def test_client_signature_override_arg(self, request_signer):
        creator = self.create_client_creator()
        config = botocore.client.Config(signature_version='foo')
        service_client = creator.create_client(
            'myservice', 'us-west-2', credentials=self.credentials,
            client_config=config)
        request_signer.assert_called_with(
            mock.ANY, mock.ANY, mock.ANY, 'foo', mock.ANY, mock.ANY)

    def test_anonymous_client_request(self):
        creator = self.create_client_creator()
        config = botocore.client.Config(signature_version=botocore.UNSIGNED)
        service_client = creator.create_client(
            'myservice', 'us-west-2', client_config=config)

        response = service_client.test_operation(Foo='one')

        # Make sure a request has been attempted
        self.assertTrue(self.endpoint.make_request.called)

        # Make sure the request parameters do NOT include auth
        # information. The service defined above for these tests
        # uses sigv4 by default (which we disable).
        params = dict((k.lower(), v) for k, v in \
            self.endpoint.make_request.call_args[0][1].items())
        self.assertNotIn('authorization', params)
        self.assertNotIn('x-amz-signature', params)

    def test_client_registers_request_created_handler(self):
        event_emitter = mock.Mock()
        creator = self.create_client_creator(event_emitter=event_emitter)
        service_client = creator.create_client(
            'myservice', 'us-west-2', credentials=self.credentials)
        event_emitter.register.assert_called_with('request-created', mock.ANY)

    def test_client_makes_call(self):
        creator = self.create_client_creator()
        service_client = creator.create_client(
            'myservice', 'us-west-2', credentials=self.credentials)

        self.assertTrue(self.endpoint_creator.create_endpoint.called)

        response = service_client.test_operation(Foo='one', Bar='two')
        self.assertEqual(response, {})

    @mock.patch('botocore.client.RequestSigner')
    def test_client_signs_call(self, signer_mock):
        creator = self.create_client_creator()
        service_client = creator.create_client(
            'myservice', 'us-west-2', credentials=self.credentials)
        request = mock.Mock()

        # Emit the request created event to see if it would be signed.
        # We tested above to ensure this event is registered when
        # a client is created. This prevents testing the entire client
        # call logic.
        service_client.meta.events.emit(
            'request-created.myservice.test_operation', request=request,
            operation_name='test_operation')

        signer_mock.return_value.sign.assert_called_with(
            'test_operation', request)

    def test_client_makes_call_with_error(self):
        error_response = {
            'Error': {'Code': 'code', 'Message': 'error occurred'}
        }
        self.endpoint.make_request.return_value = (
            mock.Mock(status_code=400), error_response)

        creator = self.create_client_creator()

        service_client = creator.create_client(
            'myservice', 'us-west-2', credentials=self.credentials)
        with self.assertRaises(client.ClientError):
            service_client.test_operation(Foo='one', Bar='two')

    def test_client_validates_params(self):
        creator = self.create_client_creator()

        service_client = creator.create_client(
            'myservice', 'us-west-2', credentials=self.credentials)
        with self.assertRaises(ParamValidationError):
            # Missing required 'Foo' param.
            service_client.test_operation(Bar='two')

    def test_client_with_custom_params(self):
        creator = self.create_client_creator()

        creator.create_client('myservice', 'us-west-2',
                              is_secure=False, verify=False)
        self.endpoint_creator.create_endpoint.assert_called_with(
            mock.ANY, 'us-west-2', is_secure=False,
            endpoint_url=None, verify=False,
            response_parser_factory=None)

    def test_client_with_endpoint_url(self):
        creator = self.create_client_creator()

        creator.create_client('myservice', 'us-west-2',
                              endpoint_url='http://custom.foo')
        self.endpoint_creator.create_endpoint.assert_called_with(
            mock.ANY, 'us-west-2', is_secure=True,
            endpoint_url='http://custom.foo', verify=None,
            response_parser_factory=None)

    def test_client_with_response_parser_factory(self):
        factory = mock.Mock()
        creator = self.create_client_creator(response_parser_factory=factory)
        creator.create_client('myservice', 'us-west-2')
        self.endpoint_creator.create_endpoint.assert_called_with(
            mock.ANY, 'us-west-2', is_secure=True,
            endpoint_url=None, verify=None,
            response_parser_factory=factory)

    def test_operation_cannot_paginate(self):
        pagination_config = {
            'pagination': {
                # Note that there's no pagination config for
                # 'TestOperation', indicating that TestOperation
                # is not pageable.
                'SomeOtherOperation': {
                    "input_token": "Marker",
                    "output_token": "Marker",
                    "more_results": "IsTruncated",
                    "limit_key": "MaxItems",
                    "result_key": "Users"
                }
            }
        }
        self.loader.load_data.return_value = pagination_config
        creator = self.create_client_creator()
        service_client = creator.create_client('myservice', 'us-west-2')
        self.assertFalse(service_client.can_paginate('test_operation'))

    def test_operation_can_paginate(self):
        pagination_config = {
            'pagination': {
                'TestOperation': {
                    "input_token": "Marker",
                    "output_token": "Marker",
                    "more_results": "IsTruncated",
                    "limit_key": "MaxItems",
                    "result_key": "Users"
                }
            }
        }
        self.loader.load_data.return_value = pagination_config
        creator = self.create_client_creator()
        service_client = creator.create_client('myservice', 'us-west-2')
        self.assertTrue(service_client.can_paginate('test_operation'))
        # Also, the config is cached, but we want to make sure we get
        # the same answer when we ask again.
        self.assertTrue(service_client.can_paginate('test_operation'))

    def test_service_has_no_pagination_configs(self):
        # This is the case where there is an actual *.paginator.json, file,
        # but the specific operation itself is not actually pageable.
        # If the loader cannot load pagination configs, it communicates
        # this by raising a DataNotFoundError.
        self.loader.load_data.side_effect = exceptions.DataNotFoundError(
            data_path='/foo')
        creator = self.create_client_creator()
        service_client = creator.create_client('myservice', 'us-west-2')
        self.assertFalse(service_client.can_paginate('test_operation'))

    def test_waiter_config_uses_service_name_not_endpoint_prefix(self):
        waiter_config = {
            'version': 2,
            'waiters': {}
        }
        self.loader.load_data.return_value = waiter_config
        creator = self.create_client_creator()
        # We're going to verify that the loader loads a service called
        # 'other-service-name', and even though the endpointPrefix is
        # 'myservice', we use 'other-service-name' for waiters/paginators, etc.
        service_client = creator.create_client('other-service-name',
                                               'us-west-2')
        self.assertEqual(service_client.waiter_names, [])
        # Note we're using other-service-name, not
        # 'myservice', which is the endpointPrefix.
        self.loader.load_data.assert_called_with(
            'aws/other-service-name/2014-01-01.waiters')

    def test_service_has_waiter_configs(self):
        waiter_config = {
            'version': 2,
            'waiters': {
                "Waiter1": {
                    'operation': 'TestOperation',
                    'delay': 5,
                    'maxAttempts': 20,
                    'acceptors': [],
                },
                "Waiter2": {
                    'operation': 'TestOperation',
                    'delay': 5,
                    'maxAttempts': 20,
                    'acceptors': [],
                },
            }
        }
        self.loader.load_data.return_value = waiter_config
        creator = self.create_client_creator()
        service_client = creator.create_client('myservice', 'us-west-2')
        self.assertEqual(sorted(service_client.waiter_names),
                         sorted(['waiter_1', 'waiter_2']))
        self.assertTrue(hasattr(service_client.get_waiter('waiter_1'), 'wait'))

    def test_service_has_no_waiter_configs(self):
        self.loader.load_data.side_effect = exceptions.DataNotFoundError(
            data_path='/foo')
        creator = self.create_client_creator()
        service_client = creator.create_client('myservice', 'us-west-2')
        self.assertEqual(service_client.waiter_names, [])
        with self.assertRaises(ValueError):
            service_client.get_waiter("unknown_waiter")

    def test_try_to_paginate_non_paginated(self):
        self.loader.load_data.side_effect = exceptions.DataNotFoundError(
            data_path='/foo')
        creator = self.create_client_creator()
        service_client = creator.create_client('myservice', 'us-west-2')
        with self.assertRaises(exceptions.OperationNotPageableError):
            service_client.get_paginator('test_operation')

    def test_successful_pagination_object_created(self):
        pagination_config = {
            'pagination': {
                'TestOperation': {
                    "input_token": "Marker",
                    "output_token": "Marker",
                    "more_results": "IsTruncated",
                    "limit_key": "MaxItems",
                    "result_key": "Users"
                }
            }
        }
        self.loader.load_data.return_value = pagination_config
        creator = self.create_client_creator()
        service_client = creator.create_client('myservice', 'us-west-2')
        paginator = service_client.get_paginator('test_operation')
        # The pagination logic itself is tested elsewhere (test_paginate.py),
        # but we can at least make sure it looks like a paginator.
        self.assertTrue(hasattr(paginator, 'paginate'))

    def test_can_set_credentials_in_client_init(self):
        creator = self.create_client_creator()
        credentials = Credentials(
            access_key='access_key', secret_key='secret_key',
            token='session_token')
        client = creator.create_client(
            'myservice', 'us-west-2', credentials=credentials)

        # Verify that we create an endpoint with a credentials object
        # matching our creds arguments.
        self.assertEqual(client._request_signer._credentials, credentials)

    def test_event_emitted_when_invoked(self):
        event_emitter = hooks.HierarchicalEmitter()
        creator = self.create_client_creator(event_emitter=event_emitter)

        calls = []
        handler = lambda **kwargs: calls.append(kwargs)
        event_emitter.register('before-call', handler)

        service_client = creator.create_client(
            'myservice', 'us-west-2', credentials=self.credentials)
        service_client.test_operation(Foo='one', Bar='two')
        self.assertEqual(len(calls), 1)

    def test_events_are_per_client(self):
        event_emitter = hooks.HierarchicalEmitter()
        creator = self.create_client_creator(event_emitter=event_emitter)

        first_calls = []
        first_handler = lambda **kwargs: first_calls.append(kwargs)

        second_calls = []
        second_handler = lambda **kwargs: second_calls.append(kwargs)

        first_client = creator.create_client(
            'myservice', 'us-west-2', credentials=self.credentials)
        second_client = creator.create_client(
            'myservice', 'us-west-2', credentials=self.credentials)

        first_client.meta.events.register('before-call', first_handler)
        second_client.meta.events.register('before-call', second_handler)

        # Now, if we invoke an operation from either client, only
        # the handlers registered with the specific client will be invoked.
        # So if we invoke the first client.
        first_client.test_operation(Foo='one', Bar='two')
        # Only first_calls is populated, not second_calls.
        self.assertEqual(len(first_calls), 1)
        self.assertEqual(len(second_calls), 0)

        # If we invoke an operation from the second client,
        # only second_calls will be populated, not first_calls.
        second_client.test_operation(Foo='one', Bar='two')
        # first_calls == 1 from the previous first_client.test_operation()
        # call.
        self.assertEqual(len(first_calls), 1)
        self.assertEqual(len(second_calls), 1)

    def test_clients_inherit_handlers_from_session(self):
        # Even though clients get their own event emitters, they still
        # inherit any handlers that were registered on the event emitter
        # at the time the client was created.
        event_emitter = hooks.HierarchicalEmitter()
        creator = self.create_client_creator(event_emitter=event_emitter)

        # So if an event handler is registered before any clients are created:

        base_calls = []
        base_handler = lambda **kwargs: base_calls.append(kwargs)
        event_emitter.register('before-call', base_handler)

        # Then any client created from this point forward from the
        # event_emitter passed into the ClientCreator will have this
        # handler.
        first_client = creator.create_client(
            'myservice', 'us-west-2', credentials=self.credentials)
        first_client.test_operation(Foo='one', Bar='two')
        self.assertEqual(len(base_calls), 1)

        # Same thing if we create another client.
        second_client = creator.create_client(
            'myservice', 'us-west-2', credentials=self.credentials)
        second_client.test_operation(Foo='one', Bar='two')
        self.assertEqual(len(base_calls), 2)

    def test_clients_inherit_only_at_create_time(self):
        # If event handlers are added to the copied event emitter
        # _after_ a client is created, we don't pick those up.
        event_emitter = hooks.HierarchicalEmitter()
        creator = self.create_client_creator(event_emitter=event_emitter)

        # 1. Create a client.
        first_client = creator.create_client(
            'myservice', 'us-west-2', credentials=self.credentials)

        # 2. Now register an event handler from the originating event emitter.
        base_calls = []
        base_handler = lambda **kwargs: base_calls.append(kwargs)
        event_emitter.register('before-call', base_handler)

        # 3. The client will _not_ see this because it already has its
        #    own copy of the event handlers.
        first_client.test_operation(Foo='one', Bar='two')
        self.assertEqual(len(base_calls), 0)

    def test_client_can_be_cloned(self):
        # Even though we're verifying that clone_client() works, we want
        # to avoid testing internal attributes.
        # Instead we try to test this via the public API:
        #   - Cloning the API with a new endpoint will use the new endopint.
        event_emitter = hooks.HierarchicalEmitter()
        creator = self.create_client_creator(event_emitter=event_emitter)

        new_endpoint = mock.Mock()
        new_endpoint.make_request.return_value = (
            mock.Mock(status_code=200),
            {'type': 'from-replaced-endpoint'})

        service_client = creator.create_client(
            'myservice', 'us-west-2', credentials=self.credentials)
        cloned = service_client.clone_client(endpoint=new_endpoint)
        response = cloned.test_operation(Foo='one', Bar='two')

        self.assertEqual(response['type'], 'from-replaced-endpoint')

    def test_client_cloned_has_copied_event_emitter(self):
        # We have a specific test for this because this value gets
        # mapped to the .meta object, so it has custom behavior.
        creator = self.create_client_creator()
        original = creator.create_client('myservice', 'us-west-2')

        cloned = original.clone_client()
        self.assertTrue(cloned.meta.events is not original.meta.events)

    def test_clients_have_meta_object(self):
        creator = self.create_client_creator()
        service_client = creator.create_client('myservice', 'us-west-2')
        self.assertTrue(hasattr(service_client, 'meta'))
        self.assertTrue(hasattr(service_client.meta, 'events'))
        # Sanity check the event emitter has an .emit() method.
        self.assertTrue(hasattr(service_client.meta.events, 'emit'))
