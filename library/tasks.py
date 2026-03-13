from celery import shared_task
from .models import Loan
from django.core.mail import send_mail, send_mass_mail
from django.conf import settings
from django.utils import timezone
from django.db import transaction
from smtplib import SMTPConnectError
from logging import getLogger


logger = getLogger()


@shared_task(
    bind=True,
    auto_retry_on=[ConnectionError, SMTPConnectError],
    retry_backoff=True,
    retry_jitter=True,
)
def send_loan_notification(self, loan_id):
    with transaction.atomic():
        loan = Loan.objects.select_for_update().get(id=loan_id)
        if loan.is_notified:
            logger.warning(f"Loan {loan.pk} is already notified")
            return

        member_email = loan.member.user.email
        book_title = loan.book.title
        send_mail(
            subject='Book Loaned Successfully',
            message=f'Hello {loan.member.user.username},\n\nYou have successfully loaned "{book_title}".\nPlease return it by the due date.',
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[member_email],
            fail_silently=False,
        )
        loan.is_notified = True
        loan.save()


@shared_task
def check_overdue_loans():
    today = timezone.now().date
    due_loans = Loan.objects.filter(due_date__lt=today, is_returned=False)

    mass_emails_data = [
        (
            'Book Loaned Successfully',
            f'Hello {loan.member.user.username},\n\nYou have to return loaned "{loan.book.title}".\nPlease return it as soon as possible',
            settings.DEFAULT_FROM_EMAIL,
            [loan.member.user.email]
        )
        for loan in due_loans
    ]
    send_mass_mail(mass_emails_data)
