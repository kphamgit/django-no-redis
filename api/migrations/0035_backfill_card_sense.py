# Backfill Card.sense for cards created before the sense FK existed.
#
# One-time reconnection: for each card that has no sense yet, find the sense it WOULD have
# matched under the old rule -- a sense whose definition equals the card's definition, under a
# part of speech whose dict entry's head_word equals the card's text -- and link it.
# Cards with no matching sense (e.g. NewCard cards, or senses whose definition was edited after
# the card was made) are left null, which is correct.

from django.db import migrations


def link_cards_to_senses(apps, schema_editor):
    Card = apps.get_model('api', 'Card')
    Sense = apps.get_model('api', 'Sense')

    for card in Card.objects.filter(sense__isnull=True):
        sense = (Sense.objects
                 .filter(definition=card.definition,
                         pos__dict_entry__head_word=card.text)
                 .first())
        if sense:
            card.sense = sense
            card.save(update_fields=['sense'])


def unlink_cards_from_senses(apps, schema_editor):
    # Reverse: simply drop the links this migration created. We can't tell which links were
    # added here vs. by later app usage, so on reverse we clear them all; re-running forward
    # re-establishes them from the (text, definition) match.
    Card = apps.get_model('api', 'Card')
    Card.objects.update(sense=None)


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0034_card_sense'),
    ]

    operations = [
        migrations.RunPython(link_cards_to_senses, unlink_cards_from_senses),
    ]
