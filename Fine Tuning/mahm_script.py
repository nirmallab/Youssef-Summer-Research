
import torch #gpu acceleration
device = "cpu"
if (torch.cuda.is_available()):
  device = "cuda"
print("device: " + device)

import h5py
def load_data(file_path):
    with h5py.File(file_path, 'r') as f:
        images = f['images'][:]
        labels = f['labels'][:]
    return images, labels #return the images and labels

import pandas as pd
import os
#os.chdir(r"\Users\youyo\OneDrive\Desktop\research") #CHANGE!!!!!
# Load the array and labels from the HDF5 file
images, labels = load_data('medium.h5') #CHANGE!!!!!

data = pd.DataFrame()

data['images'] = list(images)
data['labels'] = labels

from sklearn.model_selection import train_test_split
train_data, rest_data = train_test_split(data, train_size=0.80, shuffle=True, random_state=10)
validation_data, test_data = train_test_split(rest_data, test_size=0.5, shuffle=True, random_state=10)

train_data = train_data.reset_index(drop=True)
validation_data = validation_data.reset_index(drop=True)
test_data = test_data.reset_index(drop=True)


import os
from torch.utils.data import Dataset
from torch.utils.data import TensorDataset, DataLoader
from PIL import Image

class HEStainDataset(Dataset):
  def __init__(self, df, transform = -1):

    self.transform = transform #transformations to be applied to the images
    self.df = df #dataframe containing the images and labels
    
  def __len__(self):
    return len(self.df)

  def __getitem__(self, idx):
    if torch.is_tensor(idx):
      idx = idx.tolist()
            
    image = self.df['images'][idx] #get the image at the index
    
    image = Image.fromarray(image) #convert the image to PIL format for applying transformations to it
    assert(image.mode == 'RGB') #assert that the image is in RGB format
    
    if (self.transform != -1):
      image = self.transform(image) #apply the transformations to the image

    label = torch.tensor(self.df['labels'][idx], dtype=torch.long)

    label = label.clone().detach()


    return image, label


from torchvision import transforms

#The transformation we do for all datasets
commonTransform = transforms.Compose([
    transforms.Resize((224, 224)), #may change depending on model
    transforms.ToTensor(),
    transforms.Normalize([0.7756, 0.7037, 0.8011], [0.1126, 0.1126, 0.1126]) #different types of normalizations &  #CHANGE!!!!!!!
])

# Data augmentation transformations
augmentTransform = transforms.Compose([
    transforms.RandomHorizontalFlip(),
    transforms.RandomVerticalFlip(),
    transforms.RandomApply([transforms.RandomRotation(30)], p=0.5),
    transforms.RandomApply([transforms.ColorJitter(brightness=0.2, contrast=0.2, saturation=0.2, hue=0.2)], p=0.5) #more transoframtions?
])

# The training transformation
trainTransform = transforms.Compose([
    augmentTransform,
    commonTransform
])

trainDataset = HEStainDataset(df = train_data, transform = trainTransform)

valDataset = HEStainDataset(df = validation_data, transform = commonTransform)

testDataset = HEStainDataset(df = test_data, transform = commonTransform)

#ASSUMING YOU HAVE ALREADY DOWNLOADED THE WEIGHTS!


from sklearn.metrics import f1_score, precision_recall_fscore_support, accuracy_score
import timm
import pytorch_lightning as pl
import torch
import torch.nn as nn
import torch.optim as optim

class MulticlassModel(pl.LightningModule):
    def __init__(self, n_classes):
        super().__init__()
        model = timm.create_model("vit_large_patch16_224", img_size=224, patch_size=16, init_values=1e-5, num_classes=0, dynamic_img_size=True)
        local_dir = "./mahmood/weights"  # directory to save the model weights
        model.load_state_dict(torch.load(os.path.join(local_dir, "pytorch_model.bin"), map_location=device), strict=True)
        
        for param in model.parameters():
            param.requires_grad = False
        
        model.head = nn.Sequential(
        nn.Linear(1024, 512),
        nn.ReLU(),
        nn.Linear(512, n_classes)
        )
        
        self.model = model
        
        self.loss_fn = nn.CrossEntropyLoss()
        
        # Initialize storage for metrics
        self.training_metrics = []
        self.validation_metrics = []
        self.test_metrics = []
        
        self.validation_f1_history = []
        self.validation_accuracy_history = []
        
        self.training_epoch_history = []
        self.validation_epoch_history = []
        
        self.test_dict = {}
        
    def forward(self, x):
        return self.model(x)

    def shared_step(self, batch, stage):
        images, labels = batch
        ypred = self(images)
        loss = self.loss_fn(ypred, labels)
        _, pred_classes = torch.max(ypred, 1)
        return {
            'loss': loss,
            'labels': labels,
            'pred_classes': pred_classes
        }

    def training_step(self, batch, batch_idx):
        metrics = self.shared_step(batch, "train")
        self.training_metrics.append(metrics)
        return metrics['loss']

    def on_train_epoch_end(self):
        aggregated_metrics = {
            "train_loss": torch.stack([x["loss"] for x in self.training_metrics]).mean(),
        }
        self.log_dict(aggregated_metrics, prog_bar=False)
        self.training_epoch_history.append(aggregated_metrics["train_loss"].item())
        self.training_metrics.clear()

    def validation_step(self, batch, batch_idx):
        metrics = self.shared_step(batch, "valid")
        self.validation_metrics.append(metrics)
        return metrics['loss']

    def on_validation_epoch_end(self):
        all_labels = torch.cat([x['labels'] for x in self.validation_metrics]).cpu().numpy()
        all_pred_classes = torch.cat([x['pred_classes'] for x in self.validation_metrics]).cpu().numpy()
        f1 = f1_score(all_labels, all_pred_classes, average='weighted')
        accuracy = accuracy_score(all_labels, all_pred_classes)
        
        aggregated_metrics = {
            "validation_loss": torch.stack([x["loss"] for x in self.validation_metrics]).mean(),
            "validation_f1": f1,
            "validation_accuracy": accuracy
        }
        
        self.log_dict(aggregated_metrics, prog_bar=False)
        
        self.validation_epoch_history.append(aggregated_metrics["validation_loss"].item())
        self.validation_f1_history.append(f1)
        self.validation_accuracy_history.append(accuracy)

        self.validation_metrics.clear()

    def test_step(self, batch, batch_idx):
        metrics = self.shared_step(batch, "test")
        self.test_metrics.append(metrics)
        return metrics['loss']
    
    def on_test_epoch_end(self):
        all_labels = torch.cat([x['labels'] for x in self.test_metrics]).cpu().numpy()
        all_pred_classes = torch.cat([x['pred_classes'] for x in self.test_metrics]).cpu().numpy()
        f1 = f1_score(all_labels, all_pred_classes, average='weighted')
        accuracy = accuracy_score(all_labels, all_pred_classes)
        
        aggregated_metrics = {
            "testing_loss": torch.stack([x["loss"] for x in self.test_metrics]).mean(),
            "testing_f1": f1,
            "testing_accuracy": accuracy
        }

        self.log_dict(aggregated_metrics, prog_bar=False)

        self.test_metrics.clear()        
        
        self.test_dict = aggregated_metrics

    def configure_optimizers(self):
        return optim.Adam(self.parameters(), lr=0.0001)


batch_size = 64
train_loader = DataLoader(trainDataset, batch_size=batch_size, shuffle=True)
val_loader = DataLoader(valDataset, batch_size=batch_size, shuffle=False)
test_loader = DataLoader(testDataset, batch_size=batch_size, shuffle=False)

num_classes = 13  # Replace with the actual number of classes & CHANGE!!!!!
model = MulticlassModel(num_classes)

checkpoint_callback = pl.callbacks.ModelCheckpoint(monitor="validation_f1", mode = "max", dirpath="./mahmood/checkpoints")

trainer = pl.Trainer(max_epochs=50, callbacks=[checkpoint_callback])
trainer.fit(model, train_loader, val_loader)

trainer.test(model, dataloaders=test_loader, verbose=False)

import pandas as pd
model.test_dict["testing_loss"] = (model.test_dict)["testing_loss"].item()
testing_data = pd.DataFrame.from_dict(model.test_dict, orient='index').T
testing_data.to_csv("./testing_data.csv", index=False) #CHANGE!!!!!

valid_f1 = model.validation_f1_history[1:]
valid_acc = model.validation_accuracy_history[1:]
valid_loss = model.validation_epoch_history[1:]
valid_dict = {"validation_f1": valid_f1, "validation_accuracy": valid_acc, "validation_loss": valid_loss}
valid_data = pd.DataFrame.from_dict(valid_dict)
valid_data.to_csv("./validation_data.csv", index=False) #CHANGE!!!!!

train_loss = model.training_epoch_history
train_dict = {"train_loss": train_loss}
train_data = pd.DataFrame.from_dict(train_dict)
train_data.to_csv("./train_data.csv", index=False) #CHANGE!!!!!


print("done")

