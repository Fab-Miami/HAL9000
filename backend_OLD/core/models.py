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

class DailySummary(models.Model):
    """
    Aggressive daily summary for a past 24H cycle (4AM to 4AM Miami).
    Stores at most 10 recent daily summaries per client.
    """
    client_id = models.CharField(max_length=255, db_index=True)
    date = models.DateField(db_index=True)
    summary_text = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['date']
        unique_together = ('client_id', 'date')

    def __str__(self):
        return f"{self.client_id} - {self.date}: {self.summary_text[:30]}"

class CoreMemoryProfile(models.Model):
    """
    Evergreen, consolidated long-term background knowledge for the client.
    Synthesizes facts older than 10 days, user identity, preferences, relationships.
    """
    client_id = models.CharField(max_length=255, unique=True, db_index=True)
    profile_markdown = models.TextField()
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Core Memory Profile ({self.client_id})"

class ConversationSummary(models.Model):
    """Legacy summary table kept for backwards compatibility."""
    client_id = models.CharField(max_length=255, db_index=True)
    summary_text = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return f"{self.client_id} summary ({self.created_at.date()})"
