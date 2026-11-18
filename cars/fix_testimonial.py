with open('models.py') as f:
    content = f.read()
idx = content.find('def testimonial_photo_upload_to')
if idx >= 0:
    content = content[:idx]
content += '\n\ndef testimonial_photo_upload_to(instance, filename):\n    return "testimonials/" + str(getattr(instance, "testimonial_id", None) or "tmp") + "/" + filename\n\n\nclass TestimonialPhoto(models.Model):\n    testimonial = models.ForeignKey(Testimonial, on_delete=models.CASCADE, related_name="photos")\n    photo = models.ImageField(upload_to=testimonial_photo_upload_to)\n    uploaded_at = models.DateTimeField(auto_now_add=True)\n\n    def __str__(self):\n        return "Photo for " + str(self.testimonial)\n'
with open('models.py','w') as f:
    f.write(content)
print('done')
