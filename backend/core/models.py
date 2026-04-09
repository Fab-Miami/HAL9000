from django.db import models

class Conversation(models.Model):
    client_id = models.CharField(max_length=255, unique=True, db_index=True)
    history_data = models.JSONField(default=list)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Conversation for {self.client_id}"
