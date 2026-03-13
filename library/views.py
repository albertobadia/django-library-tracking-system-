from rest_framework import viewsets, status
from rest_framework.response import Response
from .models import Author, Book, Member, Loan
from .serializers import AuthorSerializer, BookSerializer, MemberSerializer, LoanSerializer, LoanExtendDueDateSerializer
from rest_framework.decorators import action
from django.utils import timezone
from .tasks import send_loan_notification
from django.db import transaction


class AuthorViewSet(viewsets.ModelViewSet):
    queryset = Author.objects.all()
    serializer_class = AuthorSerializer

class BookViewSet(viewsets.ModelViewSet):

    def get_queryset(self):
        if self.action in ("loan", "return_book", "extend_due_date"):
            queryset = Book.objects.select_for_update().all()
        else:
            queryset = Book.objects.all()
        return queryset.select_related("author")

    def get_serializer_class(self):
        if self.action == "extend_due_date":
            return LoanExtendDueDateSerializer
        return BookSerializer

    @action(detail=True, methods=['post'])
    def loan(self, request, pk=None):
        with transaction.atomic():
            book = self.get_object()
            if book.available_copies < 1:
                return Response({'error': 'No available copies.'}, status=status.HTTP_400_BAD_REQUEST)
            member_id = request.data.get('member_id')
            try:
                member = Member.objects.get(id=member_id)
            except Member.DoesNotExist:
                return Response({'error': 'Member does not exist.'}, status=status.HTTP_400_BAD_REQUEST)
            loan = Loan.objects.create(book=book, member=member)
            book.available_copies -= 1
            book.save()
            transaction.on_commit(
                lambda: send_loan_notification.delay(loan.pk)
            )

        return Response({'status': 'Book loaned successfully.'}, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'])
    def return_book(self, request, pk=None):
        with transaction.atomic():
            book = self.get_object()
            member_id = request.data.get('member_id')
            try:
                loan = Loan.objects.select_for_update().get(book=book, member__id=member_id, is_returned=False)
            except Loan.DoesNotExist:
                return Response({'error': 'Active loan does not exist.'}, status=status.HTTP_400_BAD_REQUEST)

            loan.is_returned = True
            loan.return_date = timezone.now().date()
            loan.save()
            book.available_copies += 1
            book.save()

        return Response({'status': 'Book returned successfully.'}, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'])
    def extend_due_date(self, request, pk=None):
        with transaction.atomic():
            loan = self.get_object()

            if loan.is_returned:
                return Response({'status': 'Cant extend already returned loan due date'}, status=status.HTTP_400_BAD_REQUEST)

            loan.due_date += request.data.additional_days
            loan.save()
        return  Response({'status': 'Loan due date additional days added'}, status=status.HTTP_200_OK)


class MemberViewSet(viewsets.ModelViewSet):
    queryset = Member.objects.all().select_related("user")
    serializer_class = MemberSerializer

class LoanViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Loan.objects.all().select_related("book", "member__user")
    serializer_class = LoanSerializer
