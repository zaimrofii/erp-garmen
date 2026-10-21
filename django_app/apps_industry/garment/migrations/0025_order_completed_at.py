from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("garment", "0024_journalentry_journalentryline_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="order",
            name="completed_at",
            field=models.DateTimeField(
                blank=True,
                db_index=True,
                help_text="Waktu order masuk DONE; null = belum selesai.",
                null=True,
                verbose_name="selesai pada",
            ),
        ),
    ]
