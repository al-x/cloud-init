# This file is part of cloud-init. See LICENSE file for license information.

from cloudinit.reporting import events
from cloudinit.reporting.handlers import HyperVKvpReportingHandler

import json
import os
import struct
import time

from cloudinit import util
from cloudinit.tests.helpers import CiTestCase


class TestKvpEncoding(CiTestCase):
    def test_encode_decode(self):
        kvp = {'key': 'key1', 'value': 'value1'}
        kvp_reporting = HyperVKvpReportingHandler()
        data = kvp_reporting._encode_kvp_item(kvp['key'], kvp['value'])
        self.assertEqual(len(data), kvp_reporting.HV_KVP_RECORD_SIZE)
        decoded_kvp = kvp_reporting._decode_kvp_item(data)
        self.assertEqual(kvp, decoded_kvp)


class TextKvpReporter(CiTestCase):
    def setUp(self):
        super(TextKvpReporter, self).setUp()
        self.tmp_file_path = self.tmp_path('kvp_pool_file')
        util.ensure_file(self.tmp_file_path)

    def test_events_with_higher_incarnation_not_over_written(self):
        reporter = HyperVKvpReportingHandler(
            kvp_file_path=self.tmp_file_path)
        self.assertEqual(0, len(list(reporter._iterate_kvps(0))))

        reporter.publish_event(
            events.ReportingEvent('foo', 'name1', 'description'))
        reporter.publish_event(
            events.ReportingEvent('foo', 'name2', 'description'))
        reporter.q.join()
        self.assertEqual(2, len(list(reporter._iterate_kvps(0))))

        reporter3 = HyperVKvpReportingHandler(
            kvp_file_path=self.tmp_file_path)
        reporter3.incarnation_no = reporter.incarnation_no - 1
        reporter3.publish_event(
            events.ReportingEvent('foo', 'name3', 'description'))
        reporter3.q.join()
        self.assertEqual(3, len(list(reporter3._iterate_kvps(0))))

    def test_finish_event_result_is_logged(self):
        reporter = HyperVKvpReportingHandler(
            kvp_file_path=self.tmp_file_path)
        reporter.publish_event(
            events.FinishReportingEvent('name2', 'description1',
                                        result=events.status.FAIL))
        reporter.q.join()
        self.assertIn('FAIL', list(reporter._iterate_kvps(0))[0]['value'])

    def test_file_operation_issue(self):
        os.remove(self.tmp_file_path)
        reporter = HyperVKvpReportingHandler(
            kvp_file_path=self.tmp_file_path)
        reporter.publish_event(
            events.FinishReportingEvent('name2', 'description1',
                                        result=events.status.FAIL))
        reporter.q.join()

    def test_event_very_long(self):
        reporter = HyperVKvpReportingHandler(
            kvp_file_path=self.tmp_file_path)
        description = 'ab' * reporter.HV_KVP_EXCHANGE_MAX_VALUE_SIZE
        long_event = events.FinishReportingEvent(
            'event_name',
            description,
            result=events.status.FAIL)
        reporter.publish_event(long_event)
        reporter.q.join()
        kvps = list(reporter._iterate_kvps(0))
        self.assertEqual(3, len(kvps))

        # restore from the kvp to see the content are all there
        full_description = ''
        for i in range(len(kvps)):
            msg_slice = json.loads(kvps[i]['value'])
            self.assertEqual(msg_slice['msg_i'], i)
            full_description += msg_slice['msg']
        self.assertEqual(description, full_description)

    def test_not_truncate_kvp_file_modified_after_boot(self):
        with open(self.tmp_file_path, "wb+") as f:
            kvp = {'key': 'key1', 'value': 'value1'}
            data = (struct.pack("%ds%ds" % (
                    HyperVKvpReportingHandler.HV_KVP_EXCHANGE_MAX_KEY_SIZE,
                    HyperVKvpReportingHandler.HV_KVP_EXCHANGE_MAX_VALUE_SIZE),
                    kvp['key'].encode('utf-8'), kvp['value'].encode('utf-8')))
            f.write(data)
        cur_time = time.time()
        os.utime(self.tmp_file_path, (cur_time, cur_time))

        # reset this because the unit test framework
        # has already polluted the class variable
        HyperVKvpReportingHandler._already_truncated_pool_file = False

        reporter = HyperVKvpReportingHandler(kvp_file_path=self.tmp_file_path)
        kvps = list(reporter._iterate_kvps(0))
        self.assertEqual(1, len(kvps))

    def test_truncate_stale_kvp_file(self):
        with open(self.tmp_file_path, "wb+") as f:
            kvp = {'key': 'key1', 'value': 'value1'}
            data = (struct.pack("%ds%ds" % (
                HyperVKvpReportingHandler.HV_KVP_EXCHANGE_MAX_KEY_SIZE,
                HyperVKvpReportingHandler.HV_KVP_EXCHANGE_MAX_VALUE_SIZE),
                kvp['key'].encode('utf-8'), kvp['value'].encode('utf-8')))
            f.write(data)

        # set the time ways back to make it look like
        # we had an old kvp file
        os.utime(self.tmp_file_path, (1000000, 1000000))

        # reset this because the unit test framework
        # has already polluted the class variable
        HyperVKvpReportingHandler._already_truncated_pool_file = False

        reporter = HyperVKvpReportingHandler(kvp_file_path=self.tmp_file_path)
        kvps = list(reporter._iterate_kvps(0))
        self.assertEqual(0, len(kvps))