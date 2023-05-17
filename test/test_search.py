import unittest
from unittest.mock import patch
from chalicelib.api import search


class TestSearch(unittest.TestCase):
    @patch('chalicelib.api._search', autospec=True)
    def test_search(self, mock_search):
        mock_search.return_value = [
            {
                'title': 'Title 1',
                'text': 'Text 1',
                'url': 'http://example.com/1',
                'text_relevance': 0.91,
                'meaning_relevance': 0.78,
                'start': '0',
            },
            {
                'title': 'Title 2',
                'text': 'Text 2',
                'url': 'http://example.com/2',
                'text_relevance': 0.9,
                'meaning_relevance': 0.98,
                'start': '0',
            },
        ]

        query = "test query"
        expected_answer = ('Лучшие результаты по вопросу "{}":\n\n'
                           '1) Title 1\nhttp://example.com/1\nРелевантность по тексту: 0.91\nРелевантность по смыслу: 0.78\n\n'
                           '2) Title 2\nhttp://example.com/2\nРелевантность по тексту: 0.9\nРелевантность по смыслу: 0.98\n\n').format(query)

        actual_answer = search(query)

        self.assertEqual(actual_answer, expected_answer)
        mock_search.assert_called_once_with(query, 5)
