import os
import openai
import pinecone

from typing import Tuple, List
from googletrans import Translator
from loguru import logger


# Telegram token
PINECONE_ENV = os.environ["PINECONE_ENV"]
PINECONE_API_KEY = os.environ["PINECONE_API_KEY"]


def remove_capslock(text):
    if len(text) == 1:
        return text
    processed_words = []
    for word in text.split():
        if word[0].isupper() and any(c.islower() for c in word[1:]):
            processed_words.append(word)
        else:
            processed_words.append(word.lower())
    res = ' '.join(processed_words)
    res = res[0].upper() + res[1:]
    return res


def _google_translate(text: str, src: str, target: str):
    translator = Translator()
    translation = translator.translate(text, src=src, dest=target)
    return translation.text


def generate_embedding(_text: str) -> Tuple[List[float], int]:
    response = openai.Embedding.create(model="text-embedding-ada-002", input=_text)
    return response["data"][0]["embedding"], response["usage"]["total_tokens"]


def _search(query: str, top_k=5):
    processed_query = _google_translate(query, "ru", "en")

    logger.info(f"Embedding model Open AI is used for search")

    query_embedding, tokens_count = generate_embedding(processed_query)
    logger.info(f"Number of tokens to build an embedding for a user query: {tokens_count}")

    index_name = 'daniel-index'

    # initialize connection to pinecone (get API key at app.pinecone.io)
    pinecone.init(
        api_key=PINECONE_API_KEY,
        environment=PINECONE_ENV)

    # check if index already exists (it shouldn't if this is first time)
    if index_name not in pinecone.list_indexes():
        pass

    # connect to index
    index = pinecone.Index(index_name)
    # view index stats
    index.describe_index_stats()

    res = index.query(query_embedding, top_k=top_k * 2, include_metadata=True)
    unique_links = set()
    mapped_result = []
    for match in res['matches']:
        if match.metadata['url'] not in unique_links:
            metadata = match['metadata']
            unique_links.add(metadata['url'])
            mapped_result.append({
                "text": metadata["text"],
                "video_title": _google_translate(remove_capslock(metadata["title"]), "ru", "en"),
                "translated_text": _google_translate(metadata["text"], "en", "ru"),
                "translated_video_title": remove_capslock(metadata["title"]),
                "youtube_link": metadata["url"],
                "start": metadata["start"],
                "relevance": match['score']
            })
        if len(mapped_result) >= top_k:
            break
    return mapped_result


def search(query):
    """
    Handler function for text messages. Performs a search and returns the top 5 results.
    """
    logger.info(f"User query: {query}")
    results = _search(query, 5)
    logger.info(f"Results: {len(results)}")

    if len(results) > 0:
        answer = 'Вот {} лучших результатов по вопросу "{}":\n\n'.format(len(results), query)
        for count, result in enumerate(results, start=1):
            answer += '{}) {}\n{}\n\n'.format(count, result['translated_video_title'],
                                              f'{result["youtube_link"]}&t={int(result["start"])}')
    else:
        answer = 'Извините, по вопросу "{}" ничего не найдено.'.format(query)

    return answer
