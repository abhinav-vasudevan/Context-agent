import re

with open('core/ingestion/doc_ingester.py', 'r') as f:
    content = f.read()

# Replace synchronous on_status calls with awaited calls, checking if it's a coroutine function
import inspect

replacement = """
        import inspect
        if on_status:
            if inspect.iscoroutinefunction(on_status):
                await on_status(f"Reading document: {file_path.name}...")
            else:
                on_status(f"Reading document: {file_path.name}...")
"""
content = re.sub(r'\s*if on_status:\s*on_status\(f"Reading document: \{file_path.name\}\.\.\."\)', replacement, content, count=1)

replacement2 = """
        if on_status:
            if inspect.iscoroutinefunction(on_status):
                await on_status(f"Document split into {len(chunks)} chunks. Storing...")
            else:
                on_status(f"Document split into {len(chunks)} chunks. Storing...")
"""
content = re.sub(r'\s*if on_status:\s*on_status\(f"Document split into \{len\(chunks\)\} chunks\. Storing\.\.\."\)', replacement2, content, count=1)

replacement3 = """
        if on_status:
            if inspect.iscoroutinefunction(on_status):
                await on_status(f"Successfully ingested {file_path.name}.")
            else:
                on_status(f"Successfully ingested {file_path.name}.")
"""
content = re.sub(r'\s*if on_status:\s*on_status\(f"Successfully ingested \{file_path.name\}\."\)', replacement3, content, count=1)

with open('core/ingestion/doc_ingester.py', 'w') as f:
    f.write(content)

print("Fixed doc_ingester.py")
