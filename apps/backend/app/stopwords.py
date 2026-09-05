"""Stopwords for the "most common words" statistic (Swedish + English)."""

SWEDISH = """
och det att i en jag hon som han på den med var sig för så till är men ett om hade de av
icke mig du henne då sin nu har inte hans honom skulle hennes där min man ej vid kunde
något från ut när efter upp vi dem vara vad över än dig kan sina här ha mot alla under
någon eller allt mycket sedan ju denna själv detta åt utan varit hur ingen mitt ni bli
blev oss din dessa några deras besks kommer vilken jo detta vart vilka vem vart hela
dess vilket sådan sådant sådana vår våra ert era mina dina sitt vars varje vissa
ska skall kanske bara också helt bra tack hej ja nej ok okej lite mer mest just precis
gör göra gjorde blir bli va åh haha jaha nja typ ju liksom alltså asså ju
""".split()

ENGLISH = """
the be to of and a in that have i it for not on with he as you do at this but his by
from they we say her she or an will my one all would there their what so up out if
about who get which go me when make can like time no just him know take people into
year your good some could them see other than then now look only come its over think
also back after use two how our work first well way even new want because any these
give day most us is are was were been has had did does im ive youre thats dont cant
yeah yes no ok okay lol haha thanks thank hi hey oh
""".split()

STOPWORDS = frozenset(SWEDISH) | frozenset(ENGLISH)
