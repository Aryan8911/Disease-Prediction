# -*- coding: utf-8 -*-
"""BIObertlstm.ipynb

Automatically generated by Colab.

Original file is located at
    https://colab.research.google.com/drive/1mj1YtoE9so2aabQ40vLiu4xA-Qmevj-R
"""

import os
import pandas as pd
import numpy as np
import tensorflow as tf
from transformers import AutoTokenizer, TFAutoModel
from tensorflow.keras.layers import LSTM, Dense, Dropout, Bidirectional, Input
from tensorflow.keras.optimizers import Adam
from sklearn.preprocessing import LabelEncoder
from sklearn.model_selection import KFold
from collections import defaultdict
import logging

# Logging configuration
logging.basicConfig(level=logging.INFO)

# Load the dataset
data = pd.read_csv('/content/Final_Updated_Diseases_Symptoms_.csv')

# Clean the dataset
data_cleaned = data.dropna(subset=['All Symptoms'])
data_cleaned['All Symptoms'] = data_cleaned['All Symptoms'].str.lower().str.strip()

# Prepare the data
X = data_cleaned['All Symptoms'].values
y = data_cleaned['Disease'].values

# Label encode the diseases
label_encoder = LabelEncoder()
y_encoded = label_encoder.fit_transform(y)

# Load BioBERT tokenizer and model
tokenizer = AutoTokenizer.from_pretrained('dmis-lab/biobert-base-cased-v1.1')
biobert_model = TFAutoModel.from_pretrained('dmis-lab/biobert-base-cased-v1.1', from_pt=True)

# Define max sequence length for padding/truncation
max_sequence_len = 150

# Function to preprocess input data (tokenize and pad)
def preprocess_input(text):
    encoded_input = tokenizer(text, padding='max_length', truncation=True, max_length=max_sequence_len, return_tensors='tf')
    return encoded_input['input_ids'], encoded_input['attention_mask']

# Custom combined BioBERT + Stacked BiLSTM model
class BioBERT_LSTM_Model(tf.keras.Model):
    def __init__(self, biobert, lstm_units, num_labels):
        super(BioBERT_LSTM_Model, self).__init__()
        self.biobert = biobert
        self.biobert.trainable = False  # Freeze BioBERT layers initially

        # Stack of multiple BiLSTM layers
        self.bilstm_1 = Bidirectional(LSTM(lstm_units, return_sequences=True, dropout=0.3, recurrent_dropout=0.3))
        self.bilstm_2 = Bidirectional(LSTM(lstm_units, return_sequences=True, dropout=0.3, recurrent_dropout=0.3))
        self.bilstm_3 = Bidirectional(LSTM(lstm_units, dropout=0.3, recurrent_dropout=0.3))

        # Dense and output layers
        self.dense = Dense(256, activation='relu')
        self.dropout = Dropout(0.5)
        self.classifier = Dense(num_labels, activation='softmax')

    def call(self, inputs):
        input_ids, attention_mask = inputs

        # BioBERT embeddings
        embeddings = self.biobert(input_ids, attention_mask=attention_mask)[0]

        # Pass through stacked BiLSTM layers
        x = self.bilstm_1(embeddings)
        x = self.bilstm_2(x)
        x = self.bilstm_3(x)

        # Dense and dropout layers
        x = self.dense(x)
        x = self.dropout(x)

        # Output classification layer
        output = self.classifier(x)
        return output

# Define the model
num_labels = len(label_encoder.classes_)  # Number of disease classes
lstm_units = 256  # Number of LSTM units
model = BioBERT_LSTM_Model(biobert_model, lstm_units, num_labels)

# Compile the model
optimizer = Adam(learning_rate=3e-5)
model.compile(optimizer=optimizer, loss='sparse_categorical_crossentropy', metrics=['accuracy'])

# Print the model summary and structure
input_ids = Input(shape=(max_sequence_len,), dtype=tf.int32, name='input_ids')
attention_mask = Input(shape=(max_sequence_len,), dtype=tf.int32, name='attention_mask')

model([input_ids, attention_mask])  # This call builds the model

# Print model summary
model.summary()

# Save and load models
model_checkpoint_path = 'biobert_lstm_model.weights.h5'

def save_model():
    model.save_weights(model_checkpoint_path)
    logging.info(f"Model saved at {model_checkpoint_path}")

def load_model():
    model.load_weights(model_checkpoint_path)
    logging.info(f"Model loaded from {model_checkpoint_path}")

# Train the model with K-Fold Cross-Validation
def train_model_with_kfold(X, y, batch_size=32, epochs=20, n_splits=5):
    input_ids_list = []
    attention_mask_list = []

    for text in X:
        input_ids, attention_mask = preprocess_input(text)
        input_ids_list.append(input_ids)
        attention_mask_list.append(attention_mask)

    input_ids_array = np.concatenate(input_ids_list, axis=0)
    attention_mask_array = np.concatenate(attention_mask_list, axis=0)

    # KFold cross-validation
    kfold = KFold(n_splits=n_splits, shuffle=True, random_state=42)
    for train_index, val_index in kfold.split(input_ids_array):
        X_train_ids, X_val_ids = input_ids_array[train_index], input_ids_array[val_index]
        X_train_mask, X_val_mask = attention_mask_array[train_index], attention_mask_array[val_index]
        y_train, y_val = y[train_index], y[val_index]

        history = model.fit(
            [X_train_ids, X_train_mask],  # Pass them as two separate arrays
            y_train,
            batch_size=batch_size,
            epochs=epochs,
            validation_data=([X_val_ids, X_val_mask], y_val)
        )

    save_model()  # Save the model after training
    return history

# Train the model
history = train_model_with_kfold(X, y_encoded)

# Dictionary to map each disease to its set of symptoms
disease_symptoms = defaultdict(set)

# Prepare a dictionary of diseases and their corresponding symptoms
for _, row in data_cleaned.iterrows():
    disease = row['Disease']
    symptoms = row['All Symptoms'].split(", ")  # Assuming symptoms are comma-separated
    disease_symptoms[disease].update(symptoms)

# Function to preprocess the symptoms (lowercase, strip, etc.)
def preprocess_symptoms(symptoms_text):
    symptoms = symptoms_text.lower().strip().split(", ")
    symptoms = [symptom.strip() for symptom in symptoms]
    return set(symptoms)

# Function to calculate the percentage of matching symptoms for each disease
def calculate_match_percentage(user_symptoms, disease_symptoms):
    user_symptom_set = preprocess_symptoms(user_symptoms)
    match_percentages = {}

    for disease, known_symptoms in disease_symptoms.items():
        matched_symptoms = user_symptom_set.intersection(known_symptoms)
        match_percentage = (len(matched_symptoms) / len(known_symptoms)) * 100
        match_percentages[disease] = match_percentage

    # Get the disease with the highest match percentage
    best_match_disease = max(match_percentages, key=match_percentages.get)
    best_match_percentage = match_percentages[best_match_disease]

    return best_match_disease, best_match_percentage

# Function to predict disease from symptoms
def predict_disease(symptoms_text):
    try:
        input_ids, attention_mask = preprocess_input([symptoms_text])
        prediction = model.predict([input_ids, attention_mask])

        # Get the predicted class
        predicted_class_index = np.argmax(prediction, axis=1)
        predicted_class = label_encoder.inverse_transform(predicted_class_index)
        return predicted_class[0]
    except Exception as e:
        logging.error(f"Error during prediction: {e}")
        return None

# Function to predict disease and show percentage of symptom match
def predict_disease_with_percentage(symptoms_text):
    try:
        # Predict disease based on model (from your existing model code)
        predicted_disease = predict_disease(symptoms_text)

        # Calculate percentage of symptoms that match the predicted disease
        best_match_disease, best_match_percentage = calculate_match_percentage(symptoms_text, disease_symptoms)

        return predicted_disease, best_match_disease, best_match_percentage
    except Exception as e:
        logging.error(f"Error during prediction: {e}")
        return None, None, 0

import re

# Function to preprocess symptoms by extracting symptoms from a sentence
def extract_symptoms_from_sentence(text, known_symptoms):
    # Convert the sentence to lowercase
    text = text.lower()

    # Extract symptoms using keyword matching
    matched_symptoms = []

    for symptom in known_symptoms:
        # Check if the symptom keyword appears in the input text
        if symptom in text:
            matched_symptoms.append(symptom)

    return ', '.join(matched_symptoms)

# Updated function to handle full sentences
def predict_disease_with_percentage_from_sentence(sentence):
    try:
        # Extract symptoms from the input sentence
        known_symptoms = set([symptom for symptoms in disease_symptoms.values() for symptom in symptoms])
        extracted_symptoms = extract_symptoms_from_sentence(sentence, known_symptoms)

        if extracted_symptoms:
            # Predict disease based on extracted symptoms
            predicted_disease = predict_disease(extracted_symptoms)

            # Calculate percentage of symptoms that match the predicted disease
            best_match_disease, best_match_percentage = calculate_match_percentage(extracted_symptoms, disease_symptoms)

            return predicted_disease, best_match_disease, best_match_percentage
        else:
            return None, None, 0  # No symptoms found
    except Exception as e:
        logging.error(f"Error during prediction: {e}")
        return None, None, 0

# Example test
user_input = "I have Loose watery stools with Abdominal cramps with Urgent need for bowel movement, Nausea, Bloating, Fever, Dehydration symptoms"
predicted_disease, best_match_disease, best_match_percentage = predict_disease_with_percentage_from_sentence(user_input)

if predicted_disease:
    print(f"Best Match Disease: {best_match_disease}")
    #print(f"Match Percentage: {best_match_percentage:.2f}%")
else:
    print("No matching symptoms found or prediction failed.")

import os
from google.colab import files
import logging

# Define the path to save the model, make sure to include the proper extension
model_save_path = "/content/biobert_lstm_modelnew.h5"

# Ensure the directory exists
os.makedirs(os.path.dirname(model_save_path), exist_ok=True)

# Save the entire model (architecture + weights)
model.save(model_save_path)

logging.info(f"Model saved at {model_save_path}")

# Download the model to your local machine
files.download(model_save_path)

import matplotlib.pyplot as plt



# Plot training & validation accuracy values
plt.figure(figsize=(12, 5))

plt.subplot(1, 2, 1)
plt.plot(history.history['accuracy'])
plt.plot(history.history['val_accuracy'])
plt.title('Model Accuracy')
plt.xlabel('Epoch')
plt.ylabel('Accuracy')
plt.legend(['Train', 'Validation'])

# Plot training & validation loss values
plt.subplot(1, 2, 2)
plt.plot(history.history['loss'])
plt.plot(history.history['val_loss'])
plt.title('Model Loss')
plt.xlabel('Epoch')
plt.ylabel('Loss')
plt.legend(['Train', 'Validation'])

plt.tight_layout()
plt.show()

import os
import re
import logging
import tensorflow as tf

# Logging configuration
logging.basicConfig(level=logging.INFO)

# Load the saved model
model_checkpoint_path = 'biobert_lstm_modelnew.h5'

# Load BioBERT tokenizer and model
tokenizer = AutoTokenizer.from_pretrained('dmis-lab/biobert-base-cased-v1.1')

# Load the model architecture
lstm_units = 256  # Set the same number of LSTM units as before

class BioBERT_LSTM_Model(tf.keras.Model):
    def __init__(self, biobert, lstm_units, num_labels):
        super(BioBERT_LSTM_Model, self).__init__()
        self.biobert = biobert
        self.biobert.trainable = False  # Freeze BioBERT layers initially

        # Stack of multiple BiLSTM layers
        self.bilstm_1 = Bidirectional(LSTM(lstm_units, return_sequences=True, dropout=0.3, recurrent_dropout=0.3))
        self.bilstm_2 = Bidirectional(LSTM(lstm_units, return_sequences=True, dropout=0.3, recurrent_dropout=0.3))
        self.bilstm_3 = Bidirectional(LSTM(lstm_units, dropout=0.3, recurrent_dropout=0.3))

        # Dense and output layers
        self.dense = Dense(256, activation='relu')
        self.dropout = Dropout(0.5)
        self.classifier = Dense(num_labels, activation='softmax')

    def call(self, inputs):
        input_ids, attention_mask = inputs

        # BioBERT embeddings
        embeddings = self.biobert(input_ids, attention_mask=attention_mask)[0]

        # Pass through stacked BiLSTM layers
        x = self.bilstm_1(embeddings)
        x = self.bilstm_2(x)
        x = self.bilstm_3(x)

        # Dense and dropout layers
        x = self.dense(x)
        x = self.dropout(x)

        # Output classification layer
        output = self.classifier(x)
        return output

# Load the BioBERT model
biobert_model = TFAutoModel.from_pretrained('dmis-lab/biobert-base-cased-v1.1', from_pt=True)
num_labels = len(label_encoder.classes_)  # Use the number of labels from your previous training data

# Create the model
model = BioBERT_LSTM_Model(biobert_model, lstm_units, num_labels)

# Compile the model (same configuration as before)
optimizer = Adam(learning_rate=3e-5)
model.compile(optimizer=optimizer, loss='sparse_categorical_crossentropy', metrics=['accuracy'])

# Load the saved weights
model.load_weights(model_checkpoint_path)
logging.info(f"Model loaded from {model_checkpoint_path}")

# Function to preprocess input data (tokenize and pad)
def preprocess_input(text):
    encoded_input = tokenizer(text, padding='max_length', truncation=True, max_length=150, return_tensors='tf')
    return encoded_input['input_ids'], encoded_input['attention_mask']

# Function to preprocess symptoms by extracting symptoms from a sentence
def extract_symptoms_from_sentence(text, known_symptoms):
    # Convert the sentence to lowercase
    text = text.lower()

    # Extract symptoms using keyword matching
    matched_symptoms = []

    for symptom in known_symptoms:
        # Check if the symptom keyword appears in the input text
        if symptom in text:
            matched_symptoms.append(symptom)

    return ', '.join(matched_symptoms)

# Updated function to handle full sentences
def predict_disease_with_percentage_from_sentence(sentence):
    try:
        # Extract symptoms from the input sentence
        known_symptoms = set([symptom for symptoms in disease_symptoms.values() for symptom in symptoms])
        extracted_symptoms = extract_symptoms_from_sentence(sentence, known_symptoms)

        if extracted_symptoms:
            # Predict disease based on extracted symptoms
            predicted_disease = predict_disease(extracted_symptoms)

            # Calculate percentage of symptoms that match the predicted disease
            best_match_disease, best_match_percentage = calculate_match_percentage(extracted_symptoms, disease_symptoms)

            return predicted_disease, best_match_disease, best_match_percentage
        else:
            return None, None, 0  # No symptoms found
    except Exception as e:
        logging.error(f"Error during prediction: {e}")
        return None, None, 0

# Example test
user_input = "I have Whitehead, Blackheads, Small red bumps Pimples with pus that Appears on face"
predicted_disease, best_match_disease, best_match_percentage = predict_disease_with_percentage_from_sentence(user_input)

if predicted_disease:
    print(f"Best Match Disease: {best_match_disease}")
    print(f"Match Percentage: {best_match_percentage:.2f}%")
else:
    print("No matching symptoms found or prediction failed.")

import re
import logging

# Logging configuration
logging.basicConfig(level=logging.INFO)

# Function to preprocess symptoms by extracting symptoms from a sentence
def extract_symptoms_from_sentence(text, known_symptoms):
    # Convert the sentence to lowercase
    text = text.lower()

    # Extract symptoms using keyword matching
    matched_symptoms = []

    for symptom in known_symptoms:
        # Check if the symptom keyword appears in the input text
        if symptom in text:
            matched_symptoms.append(symptom)

    return ', '.join(matched_symptoms)

# Updated function to handle full sentences
def predict_disease_with_percentage_from_sentence(sentence):
    try:
        # Load the known symptoms from the disease_symptoms dictionary
        known_symptoms = set([symptom for symptoms in disease_symptoms.values() for symptom in symptoms])

        # Extract symptoms from the input sentence
        extracted_symptoms = extract_symptoms_from_sentence(sentence, known_symptoms)

        if extracted_symptoms:
            # Predict disease based on extracted symptoms
            predicted_disease = predict_disease(extracted_symptoms)

            # Calculate percentage of symptoms that match the predicted disease
            best_match_disease, best_match_percentage = calculate_match_percentage(extracted_symptoms, disease_symptoms)

            return predicted_disease, best_match_disease, best_match_percentage
        else:
            return None, None, 0  # No symptoms found
    except Exception as e:
        logging.error(f"Error during prediction: {e}")
        return None, None, 0

# Function to load the saved model weights before prediction
def load_and_predict(sentence):
    try:
        # Load the saved model weights
        model_checkpoint_path = 'biobert_lstm_model.weights.h5'
        load_model()

        # Now make the prediction after loading the model
        predicted_disease, best_match_disease, best_match_percentage = predict_disease_with_percentage_from_sentence(sentence)

        return predicted_disease, best_match_disease, best_match_percentage

    except Exception as e:
        logging.error(f"Error loading model or during prediction: {e}")
        return None, None, 0

# Take real-time input from the user
while True:
    user_input = input("Enter your symptoms (or type 'exit' to quit): ")
    if user_input.lower() == 'exit':
        print("Exiting the program.")
        break

    predicted_disease, best_match_disease, best_match_percentage = load_and_predict(user_input)

    if predicted_disease:
        print(f"Best Match Disease: {best_match_disease}")
    else:
        print("No matching symptoms found or prediction failed.")