"""
Araña generica, dada una lista de urls, va a cada página, descarga todos los links y los procesa

Para usar:

scrapy crawl araña_generica -o output.json
"""

import scrapy

class PornSpider(scrapy.Spider):
    name = 'araña_generica'
    start_urls = [
            "http://digg.com/channel/entertainment",
            "http://digg.com/channel/funny",
            "http://digg.com/channel/longreads",
            "http://digg.com/channel/technology",
            "http://digg.com/channel/science",
            "http://digg.com/channel/sports",
            ]

    def parse(self, response):
        for url in response.xpath('//@href').extract():
            yield scrapy.Request(response.urljoin(url), self.parse_page)

    def parse_page(self, response):
        meta_tags = ['keywords', 'description', 'category', 'RATING']
        tags = {}
        for tag in meta_tags:
            tags[tag] = response.xpath('//meta[@name="{}"]/@content'.format(tag)).extract_first()
        url = response.urljoin(response.url)
        text = ''.join(response.xpath("//body//text()").extract()).strip()
        links = response.xpath('//@href').extract()
        return {'url': url, 'text': text, 'links': links, 'tags':tags}
