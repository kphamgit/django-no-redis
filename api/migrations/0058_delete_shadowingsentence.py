from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("api", "0057_shadowing_sentences_to_audio"),
    ]

    operations = [
        migrations.DeleteModel(name="ShadowingSentence"),
    ]
