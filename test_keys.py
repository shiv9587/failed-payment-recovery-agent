from dotenv import load_dotenv
import os


load_dotenv()

from src.razorpay_client import get_client

try:
    
    client = get_client(use_mock=False)
    
    link = client.create_payment_link(
        amount_rupees=99.0,
        customer_name="Shiv Test",
        customer_contact="+919587974808",  
        description="Test recovery link",
        reference_id="txn_local_test_001",
    )
    
    print("\n Payment Link Successfully Created!")
    print("-----------------------------------")
    print(f"Link ID   : {link.get('id')}")
    print(f"Short URL : {link.get('short_url')}")
    print(f"Status    : {link.get('status')}")
    
except Exception as e:
    print("\n Error creating payment link:")
    print(e)