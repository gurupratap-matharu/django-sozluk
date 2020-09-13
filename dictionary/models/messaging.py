import json

from django.db import models
from django.db.models.constraints import UniqueConstraint
from django.urls import reverse
from django.utils import timezone
from django.utils.functional import cached_property

from uuslug import slugify

from ..utils import smart_lower
from ..utils.serializers import ArchiveSerializer
from ..utils.validators import validate_user_text
from .managers.messaging import ConversationManager, MessageManager


class Message(models.Model):
    body = models.TextField(validators=[validate_user_text])
    sender = models.ForeignKey("Author", related_name="+", on_delete=models.CASCADE)
    recipient = models.ForeignKey("Author", related_name="+", on_delete=models.CASCADE)
    sent_at = models.DateTimeField(auto_now_add=True)
    read_at = models.DateTimeField(null=True, editable=False)
    has_receipt = models.BooleanField(default=True)

    objects = MessageManager()

    class Meta:
        ordering = ["sent_at"]
        get_latest_by = ("sent_at",)

    def __str__(self):
        return str(self.pk)

    def save(self, *args, **kwargs):
        self.body = smart_lower(self.body).strip()
        super().save(*args, **kwargs)

    def mark_read(self):
        self.read_at = timezone.now()
        self.save()


class ConversationArchive(models.Model):
    holder = models.ForeignKey("Author", on_delete=models.CASCADE)
    target = models.CharField(max_length=35)
    slug = models.SlugField()

    messages = models.TextField()  # json text
    date_created = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.__class__.__name__} holder -> {self.holder.username} target -> {self.target}"

    class Meta:
        constraints = [
            UniqueConstraint(fields=["holder", "slug"], name="unique_conversationarchive_a"),
            UniqueConstraint(fields=["holder", "target"], name="unique_conversationarchive_b"),
        ]
        ordering = ("-date_created",)

    def save(self, *args, **kwargs):
        created = self.pk is None
        super().save(*args, **kwargs)

        if created:
            self.slug = slugify(self.target)
            self.save()

    def get_absolute_url(self):
        return reverse("conversation-archive", kwargs={"slug": self.slug})

    @cached_property
    def to_json(self):
        # JSON text to Python object
        return {"holder": self.holder, "target": self.target, "messages": json.loads(self.messages)}


class Conversation(models.Model):
    holder = models.ForeignKey("Author", on_delete=models.CASCADE, related_name="conversations")
    target = models.ForeignKey("Author", on_delete=models.CASCADE, related_name="targeted_conversations")

    messages = models.ManyToManyField(Message)
    date_created = models.DateTimeField(auto_now_add=True)

    objects = ConversationManager()

    def __str__(self):
        return f"<Conversation> holder-> {self.holder.username}, target-> {self.target.username}"

    class Meta:
        constraints = [UniqueConstraint(fields=["holder", "target"], name="unique_conversation")]

    def get_absolute_url(self):
        return reverse("conversation", kwargs={"slug": self.target.slug})

    def archive(self):
        serializer = ArchiveSerializer()
        _messages = self.messages.all()

        if not _messages.exists():
            return self

        messages = serializer.serialize(
            _messages, fields=("body", "sender__username", "recipient__username", "sent_at"),
        )

        try:
            # Extend existing archive
            existant = ConversationArchive.objects.get(holder=self.holder, target=self.target.username)
            previous_messages = existant.to_json["messages"]
            previous_messages.extend(json.loads(messages))
            existant.messages = json.dumps(previous_messages)
            existant.save()
        except ConversationArchive.DoesNotExist:
            ConversationArchive.objects.create(holder=self.holder, target=self.target.username, messages=messages)

        return self.delete()

    @property
    def last_message(self):
        return self.messages.latest("sent_at")

    @property
    def collection(self):
        return self.messages.select_related("sender")
