import difflib
import re
from collections import defaultdict
from string import digits
from typing import Optional
from urllib.error import HTTPError
from urllib.request import urlopen

import requests
from bs4 import BeautifulSoup


class MovieNotFound(Exception):
    pass


def int_or_none(val: str) -> Optional[int]:
    try:
        out = int(val)
    except ValueError:
        return None

    return out


class RTScraper:
    BASE_URL = "https://www.rottentomatoes.com/api/private/v2.0"
    SEARCH_URL = "{base_url}/search".format(base_url=BASE_URL)

    def __init__(self):
        self.metadata = dict()
        self.url = None

    def extract_url(self):
        pass

    def extract_metadata(self, **kwargs):
        pass

    def _extract_section(self, section):
        pass

    @staticmethod
    def search(term, limit=10):
        r = requests.get(url=RTScraper.SEARCH_URL, params={
                         "q": term, "limit": limit})
        r.raise_for_status()
        return r.json()


class MovieScraper(RTScraper):
    def __init__(self, **kwargs):
        RTScraper.__init__(self)

        self.movie_genre = None
        self.movie_year = kwargs.get('movie_year')
        self.movie_title = kwargs.get('movie_title')

        self.url = kwargs.get('movie_url') or self.extract_url()

        movie_metadata = self.extract_metadata()
        self.critics_score = int_or_none(movie_metadata['Score_Rotten'])
        self.audience_score = int_or_none(movie_metadata['Score_Audience'])
        self.critics_count = int_or_none(movie_metadata['Critics_Count'])
        self.audience_count = int_or_none(movie_metadata['Audience_Count'])
        self.rating = movie_metadata.get('Rating')
        self.genre = movie_metadata['Genre']

    def extract_url(self) -> str:
        search_result = self.search(term=self.movie_title)

        if self.movie_year:
            search_result['movies'] = [
                movie for movie in search_result['movies']
                if movie['year'] == self.movie_year
            ]

        movie_titles = [movie['name'] for movie in search_result['movies']]
        closest = self.closest(self.movie_title, movie_titles)

        url_movie = None
        if closest:
            for movie in search_result['movies']:
                if movie['name'] == closest[0]:
                    url_movie = 'https://www.rottentomatoes.com' + movie['url']

        if not url_movie:
            raise MovieNotFound(
                'could not find movie url that would match the criteria'
            )

        return url_movie

    def extract_metadata(self, columns=('Rating', 'Genre', 'Box Office', 'Studio')):
        movie_metadata = dict()
        try:
            page_movie = urlopen(self.url)
        except HTTPError as e:
            if e.code == 404:
                # search api can return invalid urls
                raise MovieNotFound('the movie url could not be opened')

            raise e

        soup = BeautifulSoup(page_movie, "lxml")

        # Score
        score = soup.find('score-board')
        movie_metadata['Score_Rotten'] = score.attrs['tomatometerscore']
        movie_metadata['Score_Audience'] = score.attrs['audiencescore']

        critics_count = score.select(
            'a[slot="critics-count"]'
        )[0].text
        critics_count = "".join(
            ch for ch in critics_count if ch in digits
        )
        try:
            movie_metadata['Critics_Count'] = int(critics_count)
        except ValueError:
            movie_metadata['Critics_Count'] = None

        audience_count = score.select(
            'a[slot="audience-count"]'
        )[0].text
        audience_count = "".join(
            ch for ch in audience_count if ch in digits
        )
        try:
            movie_metadata['Audience_Count'] = int(audience_count)
        except ValueError:
            movie_metadata['Audience_Count'] = None

        # Movie Info
        movie_info_section = soup.find_all('div', class_='media-body')
        soup_movie_info = BeautifulSoup(str(movie_info_section[0]), "lxml")
        movie_info_length = len(soup_movie_info.find_all(
            'li', class_='meta-row clearfix'))

        for i in range(movie_info_length):
            x = soup_movie_info.find_all('li', class_='meta-row clearfix')[i]
            soup = BeautifulSoup(str(x), "lxml")
            label = soup.find(
                'div', class_='meta-label subtle').text.strip().replace(':', '')
            value = soup.find('div', class_='meta-value').text.strip()
            if label in columns:
                if label == 'Box Office':
                    value = int(value.replace('$', '').replace(',', ''))
                if label == 'Rating':
                    value = re.sub(r'\s\([^)]*\)', '', value)
                if label == 'Genre':
                    value = value.replace(' ', '').replace('\n', '').split(',')
                movie_metadata[label] = value

        movie_metadata['Genre'] = self.extract_genre(self.metadata)
        return movie_metadata

    @staticmethod
    def closest(keyword, words):
        closest_match = difflib.get_close_matches(keyword, words, cutoff=0.6)
        return closest_match

    @staticmethod
    def extract_genre(metadata):
        try:
            if 'Genre' in metadata:
                movie_genre = metadata['Genre']
            else:
                movie_genre = ['None']

        except IOError:
            movie_genre = ['None']

        return movie_genre


class CelebrityScraper(RTScraper):
    def __init__(self, **kwargs):
        RTScraper.__init__(self)
        if 'celebrity_name' in kwargs.keys():
            self.celebrity_name = kwargs['celebrity_name']
            self.extract_url()
        if 'celebrity_url' in kwargs.keys():
            self.url = kwargs['celebrity_url']

    def extract_url(self):
        search_result = self.search(term=self.celebrity_name)
        url_celebrity = 'https://www.rottentomatoes.com' + \
            search_result['actors'][0]['url']
        self.url = url_celebrity

    def _extract_section(self, section):
        page_celebrity = urlopen(self.url)
        soup = BeautifulSoup(page_celebrity, "lxml")
        selected_section = []
        try:
            if section == 'highest':
                selected_section = soup.find_all(
                    'section', class_='dynamic-poster-list')[0].text.split('\n')
            elif section == 'filmography':
                selected_section = soup.find_all(
                    'tbody', class_='celebrity-filmography__tbody')[0]
        except IOError:
            print('The parsing process returns an error.')

        return selected_section

    def extract_metadata(self, section):
        selected_section = self._extract_section(section=section)
        movie_titles = []
        if section == 'highest':
            for i in range(len(selected_section)):
                if selected_section[i].strip():
                    movie_titles.append(selected_section[i].strip())
            movie_titles.remove('Highest rated movies')
        elif section == 'filmography':
            soup_filmography = BeautifulSoup(str(selected_section), 'lxml')
            for h in soup_filmography.find_all('a'):
                try:
                    movie_titles.append(h.text.strip())
                except IOError:
                    pass

        self.metadata['movie_titles'] = list(set(movie_titles))


class DirectorScraper(RTScraper):
    def __init__(self, **kwargs):
        RTScraper.__init__(self)
        if 'director_name' in kwargs.keys():
            self.director_name = kwargs['director_name']
            self.extract_url()
        if 'director_url' in kwargs.keys():
            self.url = kwargs['director_url']
        if 'print' in kwargs.keys():
            self.print = kwargs['print']

    def extract_url(self):
        search_result = self.search(term=self.director_name)
        url_director = 'https://www.rottentomatoes.com' + \
            search_result['actors'][0]['url']
        self.url = url_director

    def extract_metadata(self):
        try:
            if self.print:
                try:
                    print(self.director_name, self.url)
                except AttributeError:
                    print(self.url)
        except AttributeError:
            pass
        page_director = urlopen(self.url)
        soup = BeautifulSoup(page_director, 'lxml')
        try:
            selected_section = soup.find_all(
                'tbody', class_='celebrity-filmography__tbody')[0]
        except IOError:
            print('The parsing process returns an error.')

        soup_filmography = BeautifulSoup(str(selected_section), 'lxml')
        movie_metadata = defaultdict(dict)
        for each_row in soup_filmography.find_all('tr'):
            is_this_a_linked_movie = each_row.find(
                'td', class_='celebrity-filmography__title').find('a')
            if is_this_a_linked_movie is None:
                next
            else:
                for each_cell in each_row.find_all('td', class_="celebrity-filmography__credits"):
                    for each_string in each_cell.stripped_strings:
                        if "Director" in each_string:
                            try:
                                this_title = each_row['data-title']
                                movie_metadata[this_title]['Year'] = each_row['data-year']
                                movie_metadata[this_title]['Score_Rotten'] = each_row['data-tomatometer']
                                movie_metadata[this_title]['Box_Office'] = each_row['data-boxoffice']
                            except IOError:
                                pass
        self.metadata = movie_metadata
