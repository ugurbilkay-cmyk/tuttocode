"""Render real queue templates with isolated synthetic jobs; no remote calls."""
from pathlib import Path
from test_test_queue import QueueTests

test = QueueTests()
test.setUp()
for _ in range(9):
    test.upload()
folder = Path(__file__).resolve().parents[1] / 'output/test-queue-dom-fixtures'
folder.mkdir(parents=True, exist_ok=True)
(folder/'selection.html').write_text(test.client.get('/admin/tests').text)
test.create()
(folder/'case.html').write_text(test.client.get(test.case).text)
test.client.close()
print('Rendered isolated selection and case templates.')
