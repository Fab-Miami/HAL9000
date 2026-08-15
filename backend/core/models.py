from django.db import models

class ConversationHistory(models.Model):
    client_id = models.CharField(max_length=255, db_index=True)
    role = models.CharField(max_length=50)  # 'user' or 'model'
    content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return f"{self.client_id} - {self.role}: {self.content[:30]}"

class ConversationSummary(models.Model):
    client_id = models.CharField(max_length=255, db_index=True)
    summary_text = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return f"{self.client_id} summary ({self.created_at.date()})"
