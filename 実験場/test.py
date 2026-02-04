import tkinter as tk
from tkinter import ttk

root = tk.Tk()
root.title("test")

label = tk.Label(root, text="test")
label.pack()
label2 = ttk.Label(root, text="test")
label2.pack()

button = tk.Button(root, text="test")
button.pack()
button2 = ttk.Button(root, text="test")
button2.pack()


root.mainloop()