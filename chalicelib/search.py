import concurrent.futures
import csv
import logging
import os
import time

import pinecone
from loguru import logger

from chalicelib.utils import google_translate, generate_embedding, get_random_list_item, get_list, measure_time, \
    extract_video_id

# Telegram token
PINECONE_ENV = os.environ["PINECONE_ENV"]
PINECONE_API_KEY = os.environ["PINECONE_API_KEY"]
INDEX_NAME = os.environ["INDEX_NAME"]



class TextSearch:
    def __init__(self):
        self.index = self.load_index()
        self.titles = self.load_titles()

    @staticmethod
    def load_titles():
        video_data = {}
        file_path = "chalicelib/cache/youtube_titles.csv"
        with open(file_path, 'r') as csv_file:
            reader = csv.DictReader(csv_file)
            for row in reader:
                video_link = row['Ссылка на видео в YouTube']
                subtitle = row['Подзаголовок']
                video_data[extract_video_id(video_link)] = subtitle

        return video_data

    @staticmethod
    def load_index():
        pinecone.init(api_key=PINECONE_API_KEY, environment=PINECONE_ENV)
        index = pinecone.Index(INDEX_NAME)
        index.describe_index_stats()
        return index

    def search_similar_meanings(self, query_embedding, max_meanings_count, filter_query):
        similar_meanings = self.index.query(query_embedding, namespace="meaning", top_k=max_meanings_count,
                                            include_metadata=False, filter=filter_query)
        return similar_meanings

    def search_similar_meanings_parallel(self, query_embedding, max_meanings_count, max_threads=10):

        def search_similar_meanings(index, query_embedding, max_meanings_count, filter_query):
            return index.query(query_embedding, namespace="meaning", top_k=max_meanings_count,
                               include_metadata=False, filter=filter_query)

        playlist_ids = get_list('chalicelib/cache/youtube_playlists.json')

        with concurrent.futures.ThreadPoolExecutor(max_workers=max_threads) as executor:
            futures = []
            for playlist_id in playlist_ids:
                future = executor.submit(search_similar_meanings,
                                         index=self.index,
                                         query_embedding=query_embedding,
                                         max_meanings_count=max_meanings_count / max_threads,
                                         filter_query={
                                             "playlist_id": {"$eq": playlist_id}
                                         })
                futures.append(future)

            meanings = []
            for future in concurrent.futures.as_completed(futures):
                result = future.result()
                if 'matches' in result:
                    meanings.extend(result['matches'])

        return {'matches': meanings}

    def search(self, query_embedding, top_k=5):
        # number of top text to be retrieved from database
        top_texts_count = 20
        # assumed to be less than that
        max_meanings_count = 1600

        start_time = time.time()
        similar_texts = self.index.query(query_embedding, namespace="text", top_k=top_texts_count,
                                         include_metadata=True)

        end_time = time.time()
        execution_time = end_time - start_time
        logger.info(f"Execution time of the similar_texts query: {execution_time} seconds")

        start_time = time.time()
        similar_meanings = self.index.query(query_embedding, namespace="meaning", top_k=max_meanings_count,
                                            include_metadata=False)
        # similar_meanings = self.search_similar_meanings_parallel(query_embedding=query_embedding,
        #                                                          max_meanings_count=max_meanings_count)
        end_time = time.time()
        execution_time = end_time - start_time
        logging.info(f"Execution time of the similar_meanings query: {execution_time} seconds")

        start_time = time.time()
        ordered_texts = self.order_by_joint_relevance(similar_texts, similar_meanings)
        end_time = time.time()
        execution_time = end_time - start_time
        logger.info(f"order_by_joint_relevance execution time: {execution_time} seconds")

        start_time = time.time()
        top_texts = {}
        for text in ordered_texts:
            video_id = text['id'].split('-')[0]
            if video_id not in top_texts or text['relevance'] > top_texts[video_id]['relevance']:
                top_texts[video_id] = text

        sorted_result = sorted(top_texts.values(), key=lambda x: x['relevance'], reverse=True)[:top_k]
        end_time = time.time()
        execution_time = end_time - start_time
        logging.info(f"Execution time of the filter out duplication code: {execution_time} seconds")

        return sorted_result

    @staticmethod
    def _compute_text_score(text, similar_meanings):
        metadata = text["metadata"]
        try:
            meaning_id = metadata["meaning_id"]
        except KeyError:
            logger.info(f"KeyError occurred for text with id: {text['id']}")
        else:
            for chapter in similar_meanings["matches"]:
                if chapter['id'] == meaning_id:
                    return chapter['score']

            return None

    def generate_title(self, video_id, metadata):
        title = ""
        if metadata:
            title = metadata["title"].replace("- Даниил Зуев расскажет", "")
        if self.titles.get(video_id):
            title = self.titles[video_id]
        return title

    def order_by_joint_relevance(self, texts, meanings):
        import re
        mapped_results = []
        for text in texts['matches']:
            text_relevance = text['score']
            meaning_relevance = self._compute_text_score(text, meanings)
            if meaning_relevance is not None:
                meaning_id = text['metadata']['meaning_id']
                video_id = re.match(r"(.*?)-t", meaning_id).group(1) if re.match(r"(.*?)-t", meaning_id) else None
                mapped_results.append({
                    'id': text['id'],
                    'meaning_id': meaning_id,
                    'relevance': 0.4 * text_relevance + 0.6 * meaning_relevance,
                    'text_relevance': text_relevance,
                    'meaning_relevance': meaning_relevance,
                    'text': text['metadata']['text'],
                    'url': f"{text['metadata']['url']}&t={int(text['metadata']['start'])}",
                    'start': text['metadata']['start'],
                    'title': self.generate_title(video_id, text['metadata']),
                    'published': str(text['metadata']['published'])
                })
            else:
                logger.warning(f"Meaning relevance is not defined {text['id']}")
        sorted_result = sorted(mapped_results, key=lambda t: t['relevance'], reverse=True)
        return sorted_result


text_search = TextSearch()


@measure_time
def search(query):
    def get_random_response():
        return get_random_list_item('chalicelib/ui/ui_results.json')

    def get_random_next_question():
        return get_random_list_item('chalicelib/ui/ui_next_question.json')

    logger.info(f"User query: {query}")

    top_k = 3
    processed_query = google_translate(query, "ru", "en")

    logger.info(f"Embedding model Open AI is used for search")
    query_embedding, tokens_count = generate_embedding(processed_query)
    logger.info(f"Number of tokens to build an embedding for a user query: {tokens_count}")

    results = text_search.search(query_embedding, top_k)
    next_question = get_random_next_question()

    logger.info(f"Results: {len(results)}")

    if len(results) > 0:
        logger.info(f"Top result: text relevance {results[0]['text_relevance']}, "
                    f"meaning relevance {results[0]['meaning_relevance']}")
        answer = '{}\n\n'.format(get_random_response())
        for result in results:
            answer += f'👉 Из сатсанга ["{result["title"]}"]({result["url"]})\n\n'
        answer += next_question

    else:
        answer = "Ой, кажется, я не смог найти точный ответ на ваш вопрос 🤔 " \
                 "Можете уточнить вопрос для более точного поиска? 🎯"

    return answer
