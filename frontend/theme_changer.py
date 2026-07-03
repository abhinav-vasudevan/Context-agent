import os


def replace_in_file(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
        
    original = content
    
    # Replace text-white with text-nude-50 (which is now dark)
    content = content.replace('text-white', 'text-nude-50')
    content = content.replace('text-[#ffffff]', 'text-nude-50')
    
    # Replace hardcoded dark backgrounds with tailwind semantic bg
    content = content.replace('bg-[#101018]', 'bg-nude-850')
    content = content.replace('bg-[#141210]', 'bg-nude-850')
    content = content.replace('bg-[#12131c]', 'bg-nude-850')
    content = content.replace('bg-[#1e1e2d]', 'bg-nude-700')
    
    # Replace in CSS files
    if filepath.endswith('.css'):
        content = content.replace('#ffffff', '#1c1917')  # White -> Dark
        content = content.replace('#000000', '#fafaf9')  # Black -> Light
        content = content.replace('#101018', '#f5f5f4')  # Dark bg -> Light bg
        content = content.replace('#141210', '#f5f5f4')
        content = content.replace('#12131c', '#f5f5f4')
        content = content.replace('#0a0a0f', '#e7e5e4')
        content = content.replace('#1c1917', '#fafaf9')

    if content != original:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f"Updated {filepath}")


def main():
    src_dir = 'src'
    for root, dirs, files in os.walk(src_dir):
        for file in files:
            if file.endswith(('.jsx', '.css', '.js')):
                replace_in_file(os.path.join(root, file))


if __name__ == "__main__":
    main()
