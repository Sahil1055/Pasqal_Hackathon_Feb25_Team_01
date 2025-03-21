import os
from sklearn.model_selection import train_test_split, KFold
from src.pvem.clinical_data_embeddings import DataPreprocessing, ClinicalDataEmbeddings
from src.train import Trainer
from src.test import Evaluator
from src.qcnn.quanvolution import PNGDataset, QCNN
import pandas as pd
import argparse
import logging
import torch
import numpy as np

class Pipeline:
    def __init__(self, args):
        self.args = args
        torch.manual_seed(42)
        logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

    def generate_data(self):
        if self.args.use_pregen:
            logging.info("Using pre-generated embeddings; skipping generation.")
            return
        # Target variable [Censored_0_progressed_1 → 1: Indicates liver cancer and 0: Indicates no progression or absence of liver cancer]
        target_column = "Censored_0_progressed_1"
        id_column = "TCIA_ID"
        embedding_dim = 128

        # Load and preprocess data
        data_preprocessing = DataPreprocessing("data/clinical_data/clinical_Data.csv")
        patient_data, patient_labels, patient_ids = data_preprocessing.preprocesses_data()

        # Split into train & test sets (80/20 split)
        train_data, test_data, train_labels, test_labels, train_ids, test_ids = train_test_split(
            patient_data, patient_labels, patient_ids, test_size=0.2, random_state=42, stratify=patient_labels
        )

        # Save train/test sets and corresponding labels as CSV 
        save_csv = True
        if save_csv: 
            train_data_df = pd.DataFrame(train_data.numpy())
            train_labels_df = pd.DataFrame({id_column: train_ids,  target_column: train_labels.numpy()})
            train_data_df.to_csv("data/train_data.csv", index=False)
            train_labels_df.to_csv("data/labels/train_labels.csv", index=False)

            test_data_df = pd.DataFrame(test_data.numpy())
            test_labels_df = pd.DataFrame({id_column: test_ids, target_column: test_labels.numpy()})
            test_data_df.to_csv("data/test_data.csv", index=False)
            test_labels_df.to_csv("data/labels/test_labels.csv", index=False)
        
        # Generate Clinical Embeddings
        # shape: [n, 38, 128]
        if self.args.data_type == 'both' or self.args.data_type == 'clinical':
            embedding_generator = ClinicalDataEmbeddings(embedding_dim=embedding_dim, target_column=target_column)
            embedding_generator.train_model(train_data, train_labels)
            embedding_generator.generate_and_save_embeddings(train_data, isTrain=True)
            embedding_generator.generate_and_save_embeddings(test_data, isTrain=False)

        # Generate Image Embeddings
        # shape: [n, 6, 6, 128]
        if self.args.data_type == 'both' or self.args.data_type == 'image':
            png_dataset = PNGDataset("data/image_data/png")
            # Get patient IDs directly from PNG dataset like in qmain.py
            all_patient_ids = sorted(list(png_dataset.data.keys()))
            # Split IDs the same way as qmain.py
            train_image_ids = all_patient_ids[:len(all_patient_ids)//2]
            test_image_ids = all_patient_ids[len(all_patient_ids)//2:]
            
            qcnn = QCNN(n_atoms=4)
            qadence_circuit = qcnn.define_qadence_circuit()
            
            # Use the image-specific IDs instead of clinical data IDs
            qcnn.process_and_save_embeddings(png_dataset, qadence_circuit, train_image_ids, patch_size=6, filename="train_embeddings.npy")
            qcnn.process_and_save_embeddings(png_dataset, qadence_circuit, test_image_ids, patch_size=6, filename="test_embeddings.npy")
        
    def run_cross_validation(self, k=5):
        """Run k-fold cross-validation"""
        logging.info(f"Running {k}-fold cross validation...")
        
        # Load preprocessed data
        data_preprocessing = DataPreprocessing("data/clinical_data/clinical_Data.csv")
        patient_data, patient_labels, patient_ids = data_preprocessing.preprocesses_data()
        
        # Setup cross-validation
        kfold = KFold(n_splits=k, shuffle=True, random_state=42)
        fold_metrics = []
        
        for fold, (train_idx, val_idx) in enumerate(kfold.split(patient_data)):
            logging.info(f"Training fold {fold+1}/{k}")
            
            # Split data
            train_data = patient_data[train_idx]
            train_labels = patient_labels[train_idx]
            val_data = patient_data[val_idx]
            val_labels = patient_labels[val_idx]
            
            # Generate embeddings for this fold
            embedding_generator = ClinicalDataEmbeddings(128)
            embedding_generator.train_model(train_data, train_labels)
            
            # Save fold data for training
            np.save(f"data/clinical_data/fold_{fold}_train_embeddings.npy", 
                    embedding_generator.model(train_data)[0].detach().numpy())
            np.save(f"data/clinical_data/fold_{fold}_val_embeddings.npy",
                    embedding_generator.model(val_data)[0].detach().numpy())
            
            # Run training on this fold
            # (You would need to modify your training code to accept fold parameters)
            
            # Collect metrics
            # fold_metrics.append({"c_index": c_index, "accuracy": accuracy, ...})
        
        # Average metrics across folds
        logging.info("Cross-validation results:")
        for metric in fold_metrics[0].keys():
            avg_value = sum(fold[metric] for fold in fold_metrics) / k
            logging.info(f"Average {metric}: {avg_value:.4f}")

    def train(self):
        logging.info("Starting Training...")
        trainer = Trainer(self.args)
        trainer.train()

    def test(self):
        logging.info("Starting Testing...")
        evaluator = Evaluator(self.args)
        evaluator.test()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=str, default='src/config/config_train.json', help="Path to config file")
    parser.add_argument("--mode", type=str, choices=["data", "train", "test"], required=True, help="Mode: data, train, or test")
    parser.add_argument("--data_type", type=str, default='both', choices=["clinical", "image", "both"], help="Which kind of embeddings to generate")
    parser.add_argument('--resume_epoch', default=None, type=int, help='resume training from this epoch, set to None for new training')
    parser.add_argument('--use_pregen', action='store_true', help='Use pre-generated embeddings')

    args = parser.parse_args()

    pipeline = Pipeline(args)
    if args.mode == "data":
        pipeline.generate_data()
    elif args.mode == "train":
        pipeline.train()
    elif args.mode == "test":
        pipeline.test()