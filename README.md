# wikitag

Use wikidata to tag wikipedia pages for NER tasks.

Still working on this :).

## The Idea

Wikipedia pages tend to represent real world entities (real or conceptual), which correspond to the words and phrases that one searches 
for in Named Entity Recognition. Most pages are connected to wikidata items. Wikidata items can be "traced back" to a class, using two 
properties: "instance of" (Douglas Adams [Q42] is an instance of a Human [Q5]), and subclass (Human is a subclass of Mammal, and so on...). In this way, all links
in wikipedia pages can be automatically tagged, according to a "schema" of categories, effectivly giving us large amount of tagged text for 
NER tasks.
