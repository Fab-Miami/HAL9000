from django.db import models

class Conversation(models.Model):
    client_id = models.CharField(max_length=255, unique=True, db_index=True)
    history_data = models.JSONField(default=list)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Conversation for {self.client_id}"

class LongTermMemory(models.Model):
    client_id = models.CharField(max_length=255, db_index=True)
    summary_text = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Summary for {self.client_id} on {self.created_at.date()}"
