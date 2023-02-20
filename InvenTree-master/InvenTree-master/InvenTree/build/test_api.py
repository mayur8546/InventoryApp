"""Unit tests for the BuildOrder API"""

from datetime import datetime, timedelta

from django.urls import reverse

from rest_framework import status

from part.models import Part
from build.models import Build, BuildItem
from stock.models import StockItem

from InvenTree.status_codes import BuildStatus
from InvenTree.api_tester import InvenTreeAPITestCase


class TestBuildAPI(InvenTreeAPITestCase):
    """Series of tests for the Build DRF API.

    - Tests for Build API
    - Tests for BuildItem API
    """

    fixtures = [
        'category',
        'part',
        'location',
        'build',
    ]

    roles = [
        'build.change',
        'build.add',
        'build.delete',
    ]

    def test_get_build_list(self):
        """Test that we can retrieve list of build objects."""
        url = reverse('api-build-list')
        response = self.client.get(url, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.assertEqual(len(response.data), 5)

        # Filter query by build status
        response = self.client.get(url, {'status': 40}, format='json')

        self.assertEqual(len(response.data), 4)

        # Filter by "active" status
        response = self.client.get(url, {'active': True}, format='json')
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]['pk'], 1)

        response = self.client.get(url, {'active': False}, format='json')
        self.assertEqual(len(response.data), 4)

        # Filter by 'part' status
        response = self.client.get(url, {'part': 25}, format='json')
        self.assertEqual(len(response.data), 1)

        # Filter by an invalid part
        response = self.client.get(url, {'part': 99999}, format='json')
        self.assertEqual(len(response.data), 0)

        # Get a certain reference
        response = self.client.get(url, {'reference': 'BO-0001'}, format='json')
        self.assertEqual(len(response.data), 1)

        # Get a certain reference
        response = self.client.get(url, {'reference': 'BO-9999XX'}, format='json')
        self.assertEqual(len(response.data), 0)

    def test_get_build_item_list(self):
        """Test that we can retrieve list of BuildItem objects."""
        url = reverse('api-build-item-list')

        response = self.client.get(url, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Test again, filtering by park ID
        response = self.client.get(url, {'part': '1'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)


class BuildAPITest(InvenTreeAPITestCase):
    """Series of tests for the Build DRF API."""

    fixtures = [
        'category',
        'part',
        'location',
        'bom',
        'build',
        'stock',
    ]

    # Required roles to access Build API endpoints
    roles = [
        'build.change',
        'build.add',
    ]


class BuildTest(BuildAPITest):
    """Unit testing for the build complete API endpoint."""

    def setUp(self):
        """Basic setup for this test suite"""
        super().setUp()

        self.build = Build.objects.get(pk=1)

        self.url = reverse('api-build-output-complete', kwargs={'pk': self.build.pk})

    def test_invalid(self):
        """Test with invalid data."""
        # Test with an invalid build ID
        self.post(
            reverse('api-build-output-complete', kwargs={'pk': 99999}),
            {},
            expected_code=400
        )

        data = self.post(self.url, {}, expected_code=400).data

        self.assertIn("This field is required", str(data['outputs']))
        self.assertIn("This field is required", str(data['location']))

        # Test with an invalid location
        data = self.post(
            self.url,
            {
                "outputs": [],
                "location": 999999,
            },
            expected_code=400
        ).data

        self.assertIn(
            "Invalid pk",
            str(data["location"])
        )

        data = self.post(
            self.url,
            {
                "outputs": [],
                "location": 1,
            },
            expected_code=400
        ).data

        self.assertIn("A list of build outputs must be provided", str(data))

        stock_item = StockItem.objects.create(
            part=self.build.part,
            quantity=100,
        )

        post_data = {
            "outputs": [
                {
                    "output": stock_item.pk,
                },
            ],
            "location": 1,
        }

        # Post with a stock item that does not match the build
        data = self.post(
            self.url,
            post_data,
            expected_code=400
        ).data

        self.assertIn(
            "Build output does not match the parent build",
            str(data["outputs"][0])
        )

        # Now, ensure that the stock item *does* match the build
        stock_item.build = self.build
        stock_item.save()

        data = self.post(
            self.url,
            post_data,
            expected_code=400,
        ).data

        self.assertIn(
            "This build output has already been completed",
            str(data["outputs"][0]["output"])
        )

    def test_complete(self):
        """Test build order completion."""
        # Initially, build should not be able to be completed
        self.assertFalse(self.build.can_complete)

        # We start without any outputs assigned against the build
        self.assertEqual(self.build.incomplete_outputs.count(), 0)

        # Create some more build outputs
        for _ in range(10):
            self.build.create_build_output(10)

        # Check that we are in a known state
        self.assertEqual(self.build.incomplete_outputs.count(), 10)
        self.assertEqual(self.build.incomplete_count, 100)
        self.assertEqual(self.build.completed, 0)

        # We shall complete 4 of these outputs
        outputs = self.build.incomplete_outputs.all()

        self.post(
            self.url,
            {
                "outputs": [{"output": output.pk} for output in outputs],
                "location": 1,
                "status": 50,  # Item requires attention
            },
            expected_code=201,
        )

        self.assertEqual(self.build.incomplete_outputs.count(), 0)

        # And there should be 10 completed outputs
        outputs = self.build.complete_outputs
        self.assertEqual(outputs.count(), 10)

        for output in outputs:
            self.assertFalse(output.is_building)
            self.assertEqual(output.build, self.build)

        self.build.refresh_from_db()
        self.assertEqual(self.build.completed, 100)

        # Try to complete the build (it should fail)
        finish_url = reverse('api-build-finish', kwargs={'pk': self.build.pk})

        response = self.post(
            finish_url,
            {},
            expected_code=400
        )

        self.assertTrue('accept_unallocated' in response.data)

        # Accept unallocated stock
        self.post(
            finish_url,
            {
                'accept_unallocated': True,
            },
            expected_code=201,
        )

        self.build.refresh_from_db()

        # Build should have been marked as complete
        self.assertTrue(self.build.is_complete)

    def test_cancel(self):
        """Test that we can cancel a BuildOrder via the API."""
        bo = Build.objects.get(pk=1)

        url = reverse('api-build-cancel', kwargs={'pk': bo.pk})

        self.assertEqual(bo.status, BuildStatus.PENDING)

        self.post(url, {}, expected_code=201)

        bo.refresh_from_db()

        self.assertEqual(bo.status, BuildStatus.CANCELLED)

    def test_delete(self):
        """Test that we can delete a BuildOrder via the API"""

        bo = Build.objects.get(pk=1)

        url = reverse('api-build-detail', kwargs={'pk': bo.pk})

        # At first we do not have the required permissions
        self.delete(
            url,
            expected_code=403,
        )

        self.assignRole('build.delete')

        # As build is currently not 'cancelled', it cannot be deleted
        self.delete(
            url,
            expected_code=400,
        )

        bo.status = BuildStatus.CANCELLED
        bo.save()

        # Now, we should be able to delete
        self.delete(
            url,
            expected_code=204,
        )

        with self.assertRaises(Build.DoesNotExist):
            Build.objects.get(pk=1)

    def test_create_delete_output(self):
        """Test that we can create and delete build outputs via the API."""
        bo = Build.objects.get(pk=1)

        n_outputs = bo.output_count

        create_url = reverse('api-build-output-create', kwargs={'pk': 1})

        # Attempt to create outputs with invalid data
        response = self.post(
            create_url,
            {
                'quantity': 'not a number',
            },
            expected_code=400
        )

        self.assertIn('A valid number is required', str(response.data))

        for q in [-100, -10.3, 0]:

            response = self.post(
                create_url,
                {
                    'quantity': q,
                },
                expected_code=400
            )

            if q == 0:
                self.assertIn('Quantity must be greater than zero', str(response.data))
            else:
                self.assertIn('Ensure this value is greater than or equal to 0', str(response.data))

        # Mark the part being built as 'trackable' (requires integer quantity)
        bo.part.trackable = True
        bo.part.save()

        response = self.post(
            create_url,
            {
                'quantity': 12.3,
            },
            expected_code=400
        )

        self.assertIn('Integer quantity required for trackable parts', str(response.data))

        # Erroneous serial numbers
        response = self.post(
            create_url,
            {
                'quantity': 5,
                'serial_numbers': '1, 2, 3, 4, 5, 6',
                'batch': 'my-batch',
            },
            expected_code=400
        )

        self.assertIn('Number of unique serial numbers (6) must match quantity (5)', str(response.data))

        # At this point, no new build outputs should have been created
        self.assertEqual(n_outputs, bo.output_count)

        # Now, create with *good* data
        response = self.post(
            create_url,
            {
                'quantity': 5,
                'serial_numbers': '1, 2, 3, 4, 5',
                'batch': 'my-batch',
            },
            expected_code=201,
        )

        # 5 new outputs have been created
        self.assertEqual(n_outputs + 5, bo.output_count)

        # Attempt to create with identical serial numbers
        response = self.post(
            create_url,
            {
                'quantity': 3,
                'serial_numbers': '1-3',
            },
            expected_code=400,
        )

        self.assertIn('The following serial numbers already exist or are invalid : 1,2,3', str(response.data))

        # Double check no new outputs have been created
        self.assertEqual(n_outputs + 5, bo.output_count)

        # Now, let's delete each build output individually via the API
        outputs = bo.build_outputs.all()

        delete_url = reverse('api-build-output-delete', kwargs={'pk': 1})

        response = self.post(
            delete_url,
            {
                'outputs': [],
            },
            expected_code=400
        )

        self.assertIn('A list of build outputs must be provided', str(response.data))

        # Mark 1 build output as complete
        bo.complete_build_output(outputs[0], self.user)

        self.assertEqual(n_outputs + 5, bo.output_count)
        self.assertEqual(1, bo.complete_count)

        # Delete all outputs at once
        # Note: One has been completed, so this should fail!
        response = self.post(
            delete_url,
            {
                'outputs': [
                    {
                        'output': output.pk,
                    } for output in outputs
                ]
            },
            expected_code=400
        )

        self.assertIn('This build output has already been completed', str(response.data))

        # No change to the build outputs
        self.assertEqual(n_outputs + 5, bo.output_count)
        self.assertEqual(1, bo.complete_count)

        # Let's delete 2 build outputs
        response = self.post(
            delete_url,
            {
                'outputs': [
                    {
                        'output': output.pk,
                    } for output in outputs[1:3]
                ]
            },
            expected_code=201
        )

        # Two build outputs have been removed
        self.assertEqual(n_outputs + 3, bo.output_count)
        self.assertEqual(1, bo.complete_count)

        # Tests for BuildOutputComplete serializer
        complete_url = reverse('api-build-output-complete', kwargs={'pk': 1})

        # Let's mark the remaining outputs as complete
        response = self.post(
            complete_url,
            {
                'outputs': [],
                'location': 4,
            },
            expected_code=400,
        )

        self.assertIn('A list of build outputs must be provided', str(response.data))

        for output in outputs[3:]:
            output.refresh_from_db()
            self.assertTrue(output.is_building)

        response = self.post(
            complete_url,
            {
                'outputs': [
                    {
                        'output': output.pk
                    } for output in outputs[3:]
                ],
                'location': 4,
            },
            expected_code=201,
        )

        # Check that the outputs have been completed
        self.assertEqual(3, bo.complete_count)

        for output in outputs[3:]:
            output.refresh_from_db()
            self.assertEqual(output.location.pk, 4)
            self.assertFalse(output.is_building)

        # Try again, with an output which has already been completed
        response = self.post(
            complete_url,
            {
                'outputs': [
                    {
                        'output': outputs.last().pk,
                    }
                ]
            },
            expected_code=400,
        )

        self.assertIn('This build output has already been completed', str(response.data))

    def test_download_build_orders(self):
        """Test that we can download a list of build orders via the API"""
        required_cols = [
            'reference',
            'status',
            'completed',
            'batch',
            'notes',
            'title',
            'part',
            'part_name',
            'id',
            'quantity',
        ]

        excluded_cols = [
            'lft', 'rght', 'tree_id', 'level',
            'metadata',
        ]

        with self.download_file(
            reverse('api-build-list'),
            {
                'export': 'csv',
            }
        ) as fo:

            data = self.process_csv(
                fo,
                required_cols=required_cols,
                excluded_cols=excluded_cols,
                required_rows=Build.objects.count()
            )

            for row in data:

                build = Build.objects.get(pk=row['id'])

                self.assertEqual(str(build.part.pk), row['part'])
                self.assertEqual(build.part.full_name, row['part_name'])

                self.assertEqual(build.reference, row['reference'])
                self.assertEqual(build.title, row['title'])


class BuildAllocationTest(BuildAPITest):
    """Unit tests for allocation of stock items against a build order.

    For this test, we will be using Build ID=1;

    - This points to Part 100 (see fixture data in part.yaml)
    - This Part already has a BOM with 4 items (see fixture data in bom.yaml)
    - There are no BomItem objects yet created for this build
    """

    def setUp(self):
        """Basic operation as part of test suite setup"""
        super().setUp()

        self.assignRole('build.add')
        self.assignRole('build.change')

        self.url = reverse('api-build-allocate', kwargs={'pk': 1})

        self.build = Build.objects.get(pk=1)

        # Record number of build items which exist at the start of each test
        self.n = BuildItem.objects.count()

    def test_build_data(self):
        """Check that our assumptions about the particular BuildOrder are correct."""
        self.assertEqual(self.build.part.pk, 100)

        # There should be 4x BOM items we can use
        self.assertEqual(self.build.part.bom_items.count(), 4)

        # No items yet allocated to this build
        self.assertEqual(self.build.allocated_stock.count(), 0)

    def test_get(self):
        """A GET request to the endpoint should return an error."""
        self.get(self.url, expected_code=405)

    def test_options(self):
        """An OPTIONS request to the endpoint should return information about the endpoint."""
        response = self.options(self.url, expected_code=200)

        self.assertIn("API endpoint to allocate stock items to a build order", str(response.data))

    def test_empty(self):
        """Test without any POST data."""
        # Initially test with an empty data set
        data = self.post(self.url, {}, expected_code=400).data

        self.assertIn('This field is required', str(data['items']))

        # Now test but with an empty items list
        data = self.post(
            self.url,
            {
                "items": []
            },
            expected_code=400
        ).data

        self.assertIn('Allocation items must be provided', str(data))

        # No new BuildItem objects have been created during this test
        self.assertEqual(self.n, BuildItem.objects.count())

    def test_missing(self):
        """Test with missing data."""
        # Missing quantity
        data = self.post(
            self.url,
            {
                "items": [
                    {
                        "bom_item": 1,  # M2x4 LPHS
                        "stock_item": 2,  # 5,000 screws available
                    }
                ]
            },
            expected_code=400
        ).data

        self.assertIn('This field is required', str(data["items"][0]["quantity"]))

        # Missing bom_item
        data = self.post(
            self.url,
            {
                "items": [
                    {
                        "stock_item": 2,
                        "quantity": 5000,
                    }
                ]
            },
            expected_code=400
        ).data

        self.assertIn("This field is required", str(data["items"][0]["bom_item"]))

        # Missing stock_item
        data = self.post(
            self.url,
            {
                "items": [
                    {
                        "bom_item": 1,
                        "quantity": 5000,
                    }
                ]
            },
            expected_code=400
        ).data

        self.assertIn("This field is required", str(data["items"][0]["stock_item"]))

        # No new BuildItem objects have been created during this test
        self.assertEqual(self.n, BuildItem.objects.count())

    def test_invalid_bom_item(self):
        """Test by passing an invalid BOM item."""
        data = self.post(
            self.url,
            {
                "items": [
                    {
                        "bom_item": 5,
                        "stock_item": 11,
                        "quantity": 500,
                    }
                ]
            },
            expected_code=400
        ).data

        self.assertIn('must point to the same part', str(data))

    def test_valid_data(self):
        """Test with valid data.

        This should result in creation of a new BuildItem object
        """
        self.post(
            self.url,
            {
                "items": [
                    {
                        "bom_item": 1,
                        "stock_item": 2,
                        "quantity": 5000,
                    }
                ]
            },
            expected_code=201
        )

        # A new BuildItem should have been created
        self.assertEqual(self.n + 1, BuildItem.objects.count())

        allocation = BuildItem.objects.last()

        self.assertEqual(allocation.quantity, 5000)
        self.assertEqual(allocation.bom_item.pk, 1)
        self.assertEqual(allocation.stock_item.pk, 2)


class BuildOverallocationTest(BuildAPITest):
    """Unit tests for over allocation of stock items against a build order.

    Using same Build ID=1 as allocation test above.
    """

    def setUp(self):
        """Basic operation as part of test suite setup"""
        super().setUp()

        self.assignRole('build.add')
        self.assignRole('build.change')

        self.build = Build.objects.get(pk=1)
        self.url = reverse('api-build-finish', kwargs={'pk': self.build.pk})

        StockItem.objects.create(part=Part.objects.get(pk=50), quantity=30)

        # Keep some state for use in later assertions, and then overallocate
        self.state = {}
        self.allocation = {}
        for i, bi in enumerate(self.build.part.bom_items.all()):
            rq = self.build.required_quantity(bi, None) + i + 1
            si = StockItem.objects.filter(part=bi.sub_part, quantity__gte=rq).first()

            self.state[bi.sub_part] = (si, si.quantity, rq)
            BuildItem.objects.create(
                build=self.build,
                stock_item=si,
                quantity=rq,
            )

        # create and complete outputs
        self.build.create_build_output(self.build.quantity)
        outputs = self.build.build_outputs.all()
        self.build.complete_build_output(outputs[0], self.user)

        # Validate expected state after set-up.
        self.assertEqual(self.build.incomplete_outputs.count(), 0)
        self.assertEqual(self.build.complete_outputs.count(), 1)
        self.assertEqual(self.build.completed, self.build.quantity)

    def test_overallocated_requires_acceptance(self):
        """Test build order cannot complete with overallocated items."""
        # Try to complete the build (it should fail due to overallocation)
        response = self.post(
            self.url,
            {},
            expected_code=400
        )
        self.assertTrue('accept_overallocated' in response.data)

        # Check stock items have not reduced at all
        for si, oq, _ in self.state.values():
            si.refresh_from_db()
            self.assertEqual(si.quantity, oq)

        # Accept overallocated stock
        self.post(
            self.url,
            {
                'accept_overallocated': 'accept',
            },
            expected_code=201,
        )

        self.build.refresh_from_db()

        # Build should have been marked as complete
        self.assertTrue(self.build.is_complete)

        # Check stock items have reduced in-line with the overallocation
        for si, oq, rq in self.state.values():
            si.refresh_from_db()
            self.assertEqual(si.quantity, oq - rq)

    def test_overallocated_can_trim(self):
        """Test build order will trim/de-allocate overallocated stock when requested."""
        self.post(
            self.url,
            {
                'accept_overallocated': 'trim',
            },
            expected_code=201,
        )

        self.build.refresh_from_db()

        # Build should have been marked as complete
        self.assertTrue(self.build.is_complete)

        # Check stock items have reduced only by bom requirement (overallocation trimmed)
        for bi in self.build.part.bom_items.all():
            si, oq, _ = self.state[bi.sub_part]
            rq = self.build.required_quantity(bi, None)
            si.refresh_from_db()
            self.assertEqual(si.quantity, oq - rq)


class BuildListTest(BuildAPITest):
    """Tests for the BuildOrder LIST API."""

    url = reverse('api-build-list')

    def test_get_all_builds(self):
        """Retrieve *all* builds via the API."""
        builds = self.get(self.url)

        self.assertEqual(len(builds.data), 5)

        builds = self.get(self.url, data={'active': True})
        self.assertEqual(len(builds.data), 1)

        builds = self.get(self.url, data={'status': BuildStatus.COMPLETE})
        self.assertEqual(len(builds.data), 4)

        builds = self.get(self.url, data={'overdue': False})
        self.assertEqual(len(builds.data), 5)

        builds = self.get(self.url, data={'overdue': True})
        self.assertEqual(len(builds.data), 0)

    def test_overdue(self):
        """Create a new build, in the past."""
        in_the_past = datetime.now().date() - timedelta(days=50)

        part = Part.objects.get(pk=50)

        Build.objects.create(
            part=part,
            reference="BO-0006",
            quantity=10,
            title='Just some thing',
            status=BuildStatus.PRODUCTION,
            target_date=in_the_past
        )

        response = self.get(self.url, data={'overdue': True})

        builds = response.data

        self.assertEqual(len(builds), 1)

    def test_sub_builds(self):
        """Test the build / sub-build relationship."""
        parent = Build.objects.get(pk=5)

        part = Part.objects.get(pk=50)

        n = Build.objects.count()

        # Make some sub builds
        for i in range(5):
            Build.objects.create(
                part=part,
                quantity=10,
                reference=f"BO-{i + 10}",
                title=f"Sub build {i}",
                parent=parent
            )

        # And some sub-sub builds
        for ii, sub_build in enumerate(Build.objects.filter(parent=parent)):

            for i in range(3):

                x = ii * 10 + i + 50

                Build.objects.create(
                    part=part,
                    reference=f"BO-{x}",
                    title=f"{sub_build.reference}-00{i}-sub",
                    quantity=40,
                    parent=sub_build
                )

        # 20 new builds should have been created!
        self.assertEqual(Build.objects.count(), (n + 20))

        Build.objects.rebuild()

        # Search by parent
        response = self.get(self.url, data={'parent': parent.pk})

        builds = response.data

        self.assertEqual(len(builds), 5)

        # Search by ancestor
        response = self.get(self.url, data={'ancestor': parent.pk})

        builds = response.data

        self.assertEqual(len(builds), 20)
